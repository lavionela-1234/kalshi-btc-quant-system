from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .automatic_signal_pipeline import AutomaticSignalPipeline
from .bars import bar_count
from .coinbase import stream_trades
from .db import DEFAULT_DB_PATH, log_event
from .live_bar_builder import LiveBarBuilder
from .trade_store import (
    initialize_trade_store,
    save_coinbase_trade,
    trade_count,
)


class CoinbaseTradeRecorder:
    """Record live Coinbase trades, bars, and technical signals."""

    def __init__(
        self,
        product_id: str = "BTC-USD",
        db_path: str | Path = DEFAULT_DB_PATH,
        status_interval: int = 100,
        bar_intervals: tuple[int, ...] = (1, 5, 60),
        bar_checkpoint_every: int = 25,
        signal_interval_seconds: int = 5,
        signal_confirmation_interval_seconds: int = 60,
        signal_bar_limit: int = 300,
        signal_min_bars: int = 20,
    ) -> None:
        self.product_id = product_id
        self.db_path = Path(db_path)
        self.status_interval = max(1, status_interval)
        self.session_count = 0

        self.bar_builder = LiveBarBuilder(
            intervals=bar_intervals,
            db_path=self.db_path,
            checkpoint_every=bar_checkpoint_every,
        )

        self.signal_pipeline = AutomaticSignalPipeline(
            product_id=self.product_id,
            primary_interval_seconds=signal_interval_seconds,
            confirmation_interval_seconds=(
                signal_confirmation_interval_seconds
            ),
            db_path=self.db_path,
            bar_limit=signal_bar_limit,
            min_bars=signal_min_bars,
        )

    async def on_trade(self, trade: dict[str, Any]) -> None:
        """Save one Coinbase trade and update bars and signals."""
        inserted = save_coinbase_trade(
            trade=trade,
            db_path=self.db_path,
        )

        if not inserted:
            return

        closed_bars = self.bar_builder.process_trade(trade)
        new_signals = []

        try:
            new_signals = self.signal_pipeline.process_closed_bars(
                closed_bars
            )
        except Exception as exc:
            log_event(
                level="ERROR",
                component="automatic_signal_pipeline",
                message="Automatic signal evaluation failed",
                details={
                    "product_id": self.product_id,
                    "error": str(exc),
                },
                db_path=self.db_path,
            )
            print(f"Signal pipeline error: {exc}")

        self.session_count += 1

        if self.session_count == 1:
            print(
                f"First trade recorded: "
                f"BTC ${float(trade['price']):,.2f}"
            )

        for signal in new_signals:
            print(
                "Signal saved | "
                f"{self.signal_pipeline.primary_interval_seconds}s | "
                f"{signal.direction} | "
                f"{signal.action} | "
                f"score {signal.score:+.1f} | "
                f"confidence {signal.confidence:.1%}"
            )

        if self.session_count % self.status_interval == 0:
            total = trade_count(self.db_path)

            bar_status = " | ".join(
                (
                    f"{interval}s bars: "
                    f"{bar_count(interval, self.product_id, self.db_path):,}"
                )
                for interval in self.bar_builder.intervals
            )

            print(
                f"Recorded {self.session_count:,} trades this session | "
                f"{total:,} total trades | "
                f"latest BTC ${float(trade['price']):,.2f} | "
                f"closed now: {len(closed_bars)} | "
                f"signals this session: "
                f"{self.signal_pipeline.generated_count:,} | "
                f"{bar_status}"
            )

    async def run(self) -> None:
        """Initialize storage and start the live market pipeline."""
        initialize_trade_store(self.db_path)

        log_event(
            level="INFO",
            component="coinbase_recorder",
            message=(
                "Coinbase live trade, bar, and signal pipeline started"
            ),
            details={
                "product_id": self.product_id,
                "database": str(self.db_path),
                "bar_intervals": list(self.bar_builder.intervals),
                "signal_interval_seconds": (
                    self.signal_pipeline.primary_interval_seconds
                ),
                "signal_confirmation_interval_seconds": (
                    self.signal_pipeline.confirmation_interval_seconds
                ),
            },
            db_path=self.db_path,
        )

        existing_count = trade_count(self.db_path)

        print("Kalshi BTC Quant System — Automatic Signal Pipeline")
        print(f"Product:         {self.product_id}")
        print(f"Database:        {self.db_path}")
        print(f"Existing trades: {existing_count:,}")
        print(
            "Live bars:       "
            + ", ".join(
                f"{interval}s"
                for interval in self.bar_builder.intervals
            )
        )
        print(
            "Automatic signal: "
            f"{self.signal_pipeline.primary_interval_seconds}s primary, "
            f"{self.signal_pipeline.confirmation_interval_seconds}s "
            "confirmation"
        )
        print("Press Control+C to stop.\n")

        try:
            await stream_trades(
                product_id=self.product_id,
                callback=self.on_trade,
            )
        finally:
            flushed_bars = self.bar_builder.flush()
            stats = self.signal_pipeline.stats()

            log_event(
                level="INFO",
                component="coinbase_recorder",
                message=(
                    "Coinbase live trade, bar, and signal pipeline stopped"
                ),
                details={
                    "session_trades": self.session_count,
                    "total_trades": trade_count(self.db_path),
                    "closed_bars": self.bar_builder.closed_bar_count,
                    "flushed_partial_bars": len(flushed_bars),
                    "late_trades": self.bar_builder.late_trade_count,
                    "checkpoints": self.bar_builder.checkpoint_count,
                    "signals_generated": stats.generated,
                    "signal_duplicate_skips": stats.duplicate_skips,
                    "signal_insufficient_data_skips": (
                        stats.insufficient_data_skips
                    ),
                    "signal_ignored_bars": stats.ignored_bars,
                },
                db_path=self.db_path,
            )

            print(
                "\nSaved "
                f"{len(flushed_bars)} active partial bars before shutdown."
            )
            print(
                "Automatic signals created this session: "
                f"{stats.generated:,}"
            )


async def main() -> None:
    recorder = CoinbaseTradeRecorder()
    await recorder.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nRecorder stopped safely.")
