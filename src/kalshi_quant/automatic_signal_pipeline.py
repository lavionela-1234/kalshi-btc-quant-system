from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from .bars import MarketBar, parse_timestamp
from .dashboard_data import recent_bars
from .db import DEFAULT_DB_PATH
from .market_signal import MarketSignal, evaluate_market_signal
from .signal_store import (
    initialize_signal_store,
    latest_market_signal,
    save_market_signal,
)


@dataclass(frozen=True)
class SignalPipelineStats:
    generated: int
    duplicate_skips: int
    insufficient_data_skips: int
    ignored_bars: int


class AutomaticSignalPipeline:
    """Create and store one technical signal per completed primary bar."""

    def __init__(
        self,
        *,
        product_id: str = "BTC-USD",
        primary_interval_seconds: int = 5,
        confirmation_interval_seconds: int = 60,
        db_path: str | Path = DEFAULT_DB_PATH,
        bar_limit: int = 300,
        min_bars: int = 20,
    ) -> None:
        if primary_interval_seconds <= 0:
            raise ValueError(
                "primary_interval_seconds must be greater than zero"
            )
        if confirmation_interval_seconds <= 0:
            raise ValueError(
                "confirmation_interval_seconds must be greater than zero"
            )
        if primary_interval_seconds == confirmation_interval_seconds:
            raise ValueError(
                "Primary and confirmation intervals must be different"
            )
        if bar_limit < min_bars:
            raise ValueError("bar_limit must be at least min_bars")
        if min_bars < 6:
            raise ValueError("min_bars must be at least 6")

        self.product_id = product_id
        self.primary_interval_seconds = primary_interval_seconds
        self.confirmation_interval_seconds = (
            confirmation_interval_seconds
        )
        self.db_path = Path(db_path)
        self.bar_limit = bar_limit
        self.min_bars = min_bars

        self.generated_count = 0
        self.duplicate_skip_count = 0
        self.insufficient_data_skip_count = 0
        self.ignored_bar_count = 0
        self.last_skip_reason: str | None = None

        initialize_signal_store(self.db_path)

    @staticmethod
    def _normalized_timestamp(value: str) -> str:
        return parse_timestamp(str(value)).isoformat()

    def _closed_primary_bars(
        self,
        closed_bars: Iterable[MarketBar],
    ) -> list[MarketBar]:
        candidates = [
            bar
            for bar in closed_bars
            if bar.product_id == self.product_id
            and bar.interval_seconds == self.primary_interval_seconds
        ]

        self.ignored_bar_count += sum(
            1
            for bar in closed_bars
            if bar not in candidates
        )

        return sorted(
            candidates,
            key=lambda bar: parse_timestamp(bar.end_time),
        )

    def _bars_through(
        self,
        *,
        interval_seconds: int,
        cutoff: pd.Timestamp,
    ) -> pd.DataFrame:
        dataframe = recent_bars(
            product_id=self.product_id,
            interval_seconds=interval_seconds,
            limit=self.bar_limit,
            db_path=self.db_path,
        )

        if dataframe.empty:
            return dataframe

        return (
            dataframe.loc[dataframe["end_time"] <= cutoff]
            .copy()
            .reset_index(drop=True)
        )

    def _is_duplicate(self, timestamp: str) -> bool:
        latest = latest_market_signal(
            product_id=self.product_id,
            interval_seconds=self.primary_interval_seconds,
            db_path=self.db_path,
        )

        if latest is None:
            return False

        return self._normalized_timestamp(
            str(latest["timestamp"])
        ) == self._normalized_timestamp(timestamp)

    def evaluate_closed_bar(
        self,
        closed_bar: MarketBar,
    ) -> MarketSignal | None:
        """Evaluate and store a signal for one completed primary bar."""
        if closed_bar.product_id != self.product_id:
            self.ignored_bar_count += 1
            return None
        if (
            closed_bar.interval_seconds
            != self.primary_interval_seconds
        ):
            self.ignored_bar_count += 1
            return None

        signal_timestamp = self._normalized_timestamp(
            closed_bar.end_time
        )

        if self._is_duplicate(signal_timestamp):
            self.duplicate_skip_count += 1
            self.last_skip_reason = (
                f"Signal already stored for {signal_timestamp}"
            )
            return None

        cutoff = pd.Timestamp(
            parse_timestamp(closed_bar.end_time)
        )

        primary_bars = self._bars_through(
            interval_seconds=self.primary_interval_seconds,
            cutoff=cutoff,
        )

        if len(primary_bars) < self.min_bars:
            self.insufficient_data_skip_count += 1
            self.last_skip_reason = (
                f"Need {self.min_bars} completed "
                f"{self.primary_interval_seconds}-second bars; "
                f"found {len(primary_bars)}"
            )
            return None

        confirmation_bars = self._bars_through(
            interval_seconds=self.confirmation_interval_seconds,
            cutoff=cutoff,
        )

        signal = evaluate_market_signal(
            primary_bars,
            confirmation_bars=(
                confirmation_bars
                if len(confirmation_bars) >= self.min_bars
                else None
            ),
            min_bars=self.min_bars,
        )

        if signal.timestamp is None:
            raise RuntimeError(
                "The technical signal did not include a timestamp"
            )

        if self._normalized_timestamp(
            signal.timestamp
        ) != signal_timestamp:
            raise RuntimeError(
                "Signal timestamp does not match the completed bar"
            )

        save_market_signal(
            signal,
            product_id=self.product_id,
            interval_seconds=self.primary_interval_seconds,
            db_path=self.db_path,
        )

        self.generated_count += 1
        self.last_skip_reason = None
        return signal

    def process_closed_bars(
        self,
        closed_bars: Iterable[MarketBar],
    ) -> list[MarketSignal]:
        """Evaluate every completed primary bar in chronological order."""
        closed_bars = list(closed_bars)
        candidates = self._closed_primary_bars(closed_bars)
        signals: list[MarketSignal] = []

        for closed_bar in candidates:
            signal = self.evaluate_closed_bar(closed_bar)
            if signal is not None:
                signals.append(signal)

        return signals

    def stats(self) -> SignalPipelineStats:
        return SignalPipelineStats(
            generated=self.generated_count,
            duplicate_skips=self.duplicate_skip_count,
            insufficient_data_skips=(
                self.insufficient_data_skip_count
            ),
            ignored_bars=self.ignored_bar_count,
        )
