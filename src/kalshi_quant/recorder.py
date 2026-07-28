from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

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
    """Record live Coinbase trades and build bars in real time."""

    def __init__(
        self,
        product_id: str = "BTC-USD",
        db_path: str | Path = DEFAULT_DB_PATH,
        status_interval: int = 100,
        bar_intervals: tuple[int, ...] = (1, 5, 60),
        bar_checkpoint_every: int = 25,
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

    async def on_trade(self, trade: dict[str, Any]) -> None:
        """Save one Coinbase trade and update all live market bars."""
        inserted = save_coinbase_trade(
            trade=trade,
            db_path=self.db_path,
        )

        if not inserted:
            return

        closed_bars = self.bar_builder.process_trade(trade)
        self.session_count += 1

        if self.session_count == 1:
            print(
                f"First trade recorded: "
                f"BTC ${float(trade['price']):,.2f}"
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
                f"{bar_status}"
            )

    async def run(self) -> None:
        """Initialize storage and start the live market-data pipeline."""
        initialize_trade_store(self.db_path)

        log_event(
            level="INFO",
            component="coinbase_recorder",
            message="Coinbase live trade and bar pipeline started",
            details={
                "product_id": self.product_id,
                "database": str(self.db_path),
                "bar_intervals": list(self.bar_builder.intervals),
            },
            db_path=self.db_path,
        )

        existing_count = trade_count(self.db_path)

        print("Kalshi BTC Quant System — Live Market Pipeline")
        print(f"Product:       {self.product_id}")
        print(f"Database:      {self.db_path}")
        print(f"Existing trades: {existing_count:,}")
        print(
            "Live bars:     "
            + ", ".join(
                f"{interval}s"
                for interval in self.bar_builder.intervals
            )
        )
        print("Press Control+C to stop.\n")

        try:
            await stream_trades(
                product_id=self.product_id,
                callback=self.on_trade,
            )
        finally:
            flushed_bars = self.bar_builder.flush()

            log_event(
                level="INFO",
                component="coinbase_recorder",
                message="Coinbase live trade and bar pipeline stopped",
                details={
                    "session_trades": self.session_count,
                    "total_trades": trade_count(self.db_path),
                    "closed_bars": self.bar_builder.closed_bar_count,
                    "flushed_partial_bars": len(flushed_bars),
                    "late_trades": self.bar_builder.late_trade_count,
                    "checkpoints": self.bar_builder.checkpoint_count,
                },
                db_path=self.db_path,
            )

            print(
                "\nSaved "
                f"{len(flushed_bars)} active partial bars before shutdown."
            )


async def main() -> None:
    recorder = CoinbaseTradeRecorder()
    await recorder.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nRecorder stopped safely.")
