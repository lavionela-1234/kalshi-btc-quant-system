from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .bars import (
    MarketBar,
    calculate_volume_imbalance,
    floor_timestamp,
    initialize_bar_store,
    iso_timestamp,
    latest_bar,
    parse_timestamp,
    save_market_bar,
)
from .db import DEFAULT_DB_PATH


@dataclass
class _ActiveBar:
    """Mutable in-memory representation of one active market bar."""

    product_id: str
    interval_seconds: int
    start_time: datetime
    end_time: datetime

    open: float
    high: float
    low: float
    close: float

    volume: float
    trade_count: int
    buy_volume: float
    sell_volume: float

    first_trade_time: datetime
    last_trade_time: datetime

    @classmethod
    def from_trade(
        cls,
        trade: dict[str, Any],
        interval_seconds: int,
    ) -> "_ActiveBar":
        timestamp = parse_timestamp(str(trade["timestamp"]))
        start_time = floor_timestamp(timestamp, interval_seconds)
        end_time = start_time + timedelta(seconds=interval_seconds)

        price = float(trade["price"])
        size = float(trade["size"])
        side = str(trade.get("side", "")).upper()

        return cls(
            product_id=str(trade["product_id"]),
            interval_seconds=interval_seconds,
            start_time=start_time,
            end_time=end_time,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=size,
            trade_count=1,
            buy_volume=size if side == "BUY" else 0.0,
            sell_volume=size if side == "SELL" else 0.0,
            first_trade_time=timestamp,
            last_trade_time=timestamp,
        )

    @classmethod
    def from_stored_bar(
        cls,
        stored_bar: dict[str, Any],
        trade_timestamp: datetime,
    ) -> "_ActiveBar":
        """
        Restore a previously checkpointed partial bar.

        Coinbase trades normally arrive in chronological order. The stored
        close is therefore treated as the close immediately before the next
        live trade is applied.
        """
        start_time = parse_timestamp(str(stored_bar["start_time"]))
        end_time = parse_timestamp(str(stored_bar["end_time"]))

        return cls(
            product_id=str(stored_bar["product_id"]),
            interval_seconds=int(stored_bar["interval_seconds"]),
            start_time=start_time,
            end_time=end_time,
            open=float(stored_bar["open"]),
            high=float(stored_bar["high"]),
            low=float(stored_bar["low"]),
            close=float(stored_bar["close"]),
            volume=float(stored_bar["volume"]),
            trade_count=int(stored_bar["trade_count"]),
            buy_volume=float(stored_bar["buy_volume"]),
            sell_volume=float(stored_bar["sell_volume"]),
            first_trade_time=start_time,
            last_trade_time=trade_timestamp,
        )

    def update(self, trade: dict[str, Any]) -> None:
        """Apply one normalized Coinbase trade to this active bar."""
        timestamp = parse_timestamp(str(trade["timestamp"]))
        price = float(trade["price"])
        size = float(trade["size"])
        side = str(trade.get("side", "")).upper()

        if timestamp < self.first_trade_time:
            self.open = price
            self.first_trade_time = timestamp

        if timestamp >= self.last_trade_time:
            self.close = price
            self.last_trade_time = timestamp

        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.volume += size
        self.trade_count += 1

        if side == "BUY":
            self.buy_volume += size
        elif side == "SELL":
            self.sell_volume += size

    def to_market_bar(self) -> MarketBar:
        """Convert the active bar to the immutable database model."""
        return MarketBar(
            product_id=self.product_id,
            interval_seconds=self.interval_seconds,
            start_time=iso_timestamp(self.start_time),
            end_time=iso_timestamp(self.end_time),
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            trade_count=self.trade_count,
            buy_volume=self.buy_volume,
            sell_volume=self.sell_volume,
            volume_imbalance=calculate_volume_imbalance(
                self.buy_volume,
                self.sell_volume,
            ),
        )


class LiveBarBuilder:
    """
    Build several OHLCV intervals from the live Coinbase trade stream.

    Completed bars are saved immediately. Active bars are periodically
    checkpointed so the dashboard can display the current interval and the
    pipeline can resume cleanly after a restart.
    """

    def __init__(
        self,
        intervals: Iterable[int] = (1, 5, 60),
        db_path: str | Path = DEFAULT_DB_PATH,
        checkpoint_every: int = 25,
    ) -> None:
        normalized_intervals = tuple(
            sorted({int(interval) for interval in intervals})
        )

        if not normalized_intervals:
            raise ValueError("At least one bar interval is required")

        if any(interval <= 0 for interval in normalized_intervals):
            raise ValueError("Bar intervals must be greater than zero")

        if checkpoint_every < 0:
            raise ValueError("checkpoint_every cannot be negative")

        self.intervals = normalized_intervals
        self.db_path = Path(db_path)
        self.checkpoint_every = checkpoint_every

        self._active: dict[tuple[str, int], _ActiveBar] = {}
        self.processed_trade_count = 0
        self.closed_bar_count = 0
        self.checkpoint_count = 0
        self.late_trade_count = 0

        initialize_bar_store(self.db_path)

    def _load_or_create_active_bar(
        self,
        trade: dict[str, Any],
        interval_seconds: int,
        timestamp: datetime,
        bar_start: datetime,
    ) -> _ActiveBar:
        """
        Resume a checkpointed bar when possible; otherwise create a new bar.
        """
        product_id = str(trade["product_id"])

        stored = latest_bar(
            interval_seconds=interval_seconds,
            product_id=product_id,
            db_path=self.db_path,
        )

        if stored is not None:
            stored_start = parse_timestamp(str(stored["start_time"]))

            if stored_start == bar_start:
                restored = _ActiveBar.from_stored_bar(
                    stored_bar=stored,
                    trade_timestamp=timestamp,
                )
                restored.update(trade)
                return restored

        return _ActiveBar.from_trade(
            trade=trade,
            interval_seconds=interval_seconds,
        )

    def process_trade(
        self,
        trade: dict[str, Any],
    ) -> list[MarketBar]:
        """
        Apply one normalized trade to every configured interval.

        Returns any bars that were closed by this trade.
        """
        required_fields = {
            "product_id",
            "timestamp",
            "price",
            "size",
        }
        missing = required_fields.difference(trade)

        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(
                f"Trade is missing required fields: {missing_list}"
            )

        timestamp = parse_timestamp(str(trade["timestamp"]))
        product_id = str(trade["product_id"])
        closed_bars: list[MarketBar] = []

        for interval_seconds in self.intervals:
            bar_start = floor_timestamp(
                timestamp,
                interval_seconds,
            )
            key = (product_id, interval_seconds)
            active = self._active.get(key)

            if active is None:
                self._active[key] = self._load_or_create_active_bar(
                    trade=trade,
                    interval_seconds=interval_seconds,
                    timestamp=timestamp,
                    bar_start=bar_start,
                )
                continue

            if bar_start == active.start_time:
                active.update(trade)
                continue

            if bar_start < active.start_time:
                # The raw trade remains safely stored in coinbase_trades.
                # A later offline rebuild can incorporate rare late arrivals.
                self.late_trade_count += 1
                continue

            completed = active.to_market_bar()
            save_market_bar(
                bar=completed,
                db_path=self.db_path,
            )
            closed_bars.append(completed)
            self.closed_bar_count += 1

            self._active[key] = self._load_or_create_active_bar(
                trade=trade,
                interval_seconds=interval_seconds,
                timestamp=timestamp,
                bar_start=bar_start,
            )

        self.processed_trade_count += 1

        if (
            self.checkpoint_every > 0
            and self.processed_trade_count % self.checkpoint_every == 0
        ):
            self.checkpoint()

        return closed_bars

    def checkpoint(self) -> int:
        """Upsert all active bars without clearing them."""
        for active in self._active.values():
            save_market_bar(
                bar=active.to_market_bar(),
                db_path=self.db_path,
            )

        saved_count = len(self._active)

        if saved_count:
            self.checkpoint_count += 1

        return saved_count

    def flush(self) -> list[MarketBar]:
        """
        Save all active partial bars and clear in-memory state.

        This should be called when the recorder shuts down.
        """
        flushed: list[MarketBar] = []

        for active in self._active.values():
            bar = active.to_market_bar()
            save_market_bar(
                bar=bar,
                db_path=self.db_path,
            )
            flushed.append(bar)

        self._active.clear()
        return flushed

    @property
    def active_bar_count(self) -> int:
        """Return the number of currently active interval bars."""
        return len(self._active)
