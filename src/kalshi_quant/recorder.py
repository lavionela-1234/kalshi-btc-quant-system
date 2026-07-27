from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .coinbase import stream_trades
from .db import DEFAULT_DB_PATH, log_event
from .trade_store import (
    initialize_trade_store,
    save_coinbase_trade,
    trade_count,
)


class CoinbaseTradeRecorder:
    """Record live Coinbase trades into SQLite."""

    def __init__(
        self,
        product_id: str = "BTC-USD",
        db_path: str | Path = DEFAULT_DB_PATH,
        status_interval: int = 100,
    ) -> None:
        self.product_id = product_id
        self.db_path = Path(db_path)
        self.status_interval = max(1, status_interval)
        self.session_count = 0

    async def on_trade(self, trade: dict[str, Any]) -> None:
        """Save each Coinbase trade received by the WebSocket."""
        inserted = save_coinbase_trade(
            trade=trade,
            db_path=self.db_path,
        )

        if not inserted:
            return

        self.session_count += 1

        if self.session_count == 1:
            print(
                f"First trade recorded: "
                f"BTC ${trade['price']:,.2f}"
            )

        if self.session_count % self.status_interval == 0:
            total = trade_count(self.db_path)

            print(
                f"Recorded {self.session_count:,} trades this session | "
                f"{total:,} total trades | "
                f"latest BTC ${trade['price']:,.2f}"
            )

    async def run(self) -> None:
        """Initialize the database and start recording."""
        initialize_trade_store(self.db_path)

        log_event(
            level="INFO",
            component="coinbase_recorder",
            message="Coinbase trade recorder started",
            details={
                "product_id": self.product_id,
                "database": str(self.db_path),
            },
            db_path=self.db_path,
        )

        existing_count = trade_count(self.db_path)

        print("Kalshi BTC Quant System — Coinbase Recorder")
        print(f"Product:  {self.product_id}")
        print(f"Database: {self.db_path}")
        print(f"Existing trades: {existing_count:,}")
        print("Press Control+C to stop.\n")

        try:
            await stream_trades(
                product_id=self.product_id,
                callback=self.on_trade,
            )
        finally:
            log_event(
                level="INFO",
                component="coinbase_recorder",
                message="Coinbase trade recorder stopped",
                details={
                    "session_trades": self.session_count,
                    "total_trades": trade_count(self.db_path),
                },
                db_path=self.db_path,
            )


async def main() -> None:
    recorder = CoinbaseTradeRecorder()
    await recorder.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nRecorder stopped safely.")