from __future__ import annotations

import asyncio
from pathlib import Path
from time import monotonic
from typing import Any

from .automatic_signal_pipeline import AutomaticSignalPipeline
from .bars import bar_count
from .coinbase import stream_trades
from .config import Settings
from .db import DEFAULT_DB_PATH, log_event
from .live_bar_builder import LiveBarBuilder
from .paper_trade_lifecycle import (
    PaperTradeSettlementEngine,
)
from .paper_trading_engine import PaperTradingEngine
from .trade_store import (
    initialize_trade_store,
    save_coinbase_trade,
    trade_count,
)


class CoinbaseTradeRecorder:
    """Record trades, bars, signals, and paper lifecycle events."""

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
        settings: Settings | None = None,
    ) -> None:
        self.product_id = product_id
        self.db_path = Path(db_path)
        self.status_interval = max(1, status_interval)
        self.session_count = 0
        self.settings = settings or Settings()

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

        self.paper_engine = PaperTradingEngine(
            settings=self.settings,
            db_path=self.db_path,
        )
        self.settlement_engine = PaperTradeSettlementEngine(
            settings=self.settings,
            rest_client=self.paper_engine.rest,
            db_path=self.db_path,
        )
        self.settlement_check_seconds = max(
            1.0,
            self.settings.paper_settlement_check_seconds,
        )
        self._last_settlement_check = 0.0

    async def _maybe_settle_paper_trades(
        self,
        *,
        force: bool = False,
    ) -> None:
        now = monotonic()

        if (
            not force
            and now - self._last_settlement_check
            < self.settlement_check_seconds
        ):
            return

        self._last_settlement_check = now

        try:
            batch = await asyncio.to_thread(
                self.settlement_engine.settle_open_trades
            )
        except Exception as exc:
            log_event(
                level="ERROR",
                component="paper_trade_settlement",
                message="Paper settlement check failed",
                details={"error": str(exc)},
                db_path=self.db_path,
            )
            print(f"Settlement engine error: {exc}")
            return

        for outcome in batch.outcomes:
            if not outcome.created:
                continue

            result = "WIN" if outcome.won else "LOSS"
            print(
                "Paper settlement | "
                f"{outcome.market_ticker} | "
                f"{outcome.side} | "
                f"{result} | "
                f"P&L ${outcome.pnl:+,.2f} | "
                f"bankroll ${outcome.bankroll_after:,.2f} | "
                f"drawdown {outcome.drawdown:.1%}"
            )

        if batch.errors:
            print(
                "Paper settlement check completed with "
                f"{batch.errors} error(s)."
            )

    async def on_trade(self, trade: dict[str, Any]) -> None:
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

            try:
                outcome = await asyncio.to_thread(
                    self.paper_engine.process_signal,
                    signal=signal,
                    btc_price=float(trade["price"]),
                )
                print(
                    "Paper decision | "
                    f"{outcome.decision} | "
                    f"{outcome.side or '-'} | "
                    f"edge {outcome.edge:+.1%} | "
                    f"{outcome.contracts} contracts | "
                    f"${outcome.stake:,.2f} | "
                    f"{outcome.reason}"
                )
            except Exception as exc:
                log_event(
                    level="ERROR",
                    component="paper_trading_engine",
                    message="Paper-trading evaluation failed",
                    details={
                        "product_id": self.product_id,
                        "error": str(exc),
                    },
                    db_path=self.db_path,
                )
                print(f"Paper engine error: {exc}")

        await self._maybe_settle_paper_trades()

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
                f"signals: {self.signal_pipeline.generated_count:,} | "
                f"paper opens: {self.paper_engine.opened_count:,} | "
                f"paper settlements: "
                f"{self.settlement_engine.settled_count:,} | "
                f"{bar_status}"
            )

    async def run(self) -> None:
        initialize_trade_store(self.db_path)

        log_event(
            level="INFO",
            component="coinbase_recorder",
            message=(
                "Coinbase bars, signals, and paper lifecycle "
                "pipeline started"
            ),
            details={
                "product_id": self.product_id,
                "database": str(self.db_path),
                "bar_intervals": list(self.bar_builder.intervals),
                "paper_mode": self.settings.paper_mode,
                "kalshi_market_ticker": (
                    self.settings.kalshi_market_ticker
                ),
                "settlement_check_seconds": (
                    self.settlement_check_seconds
                ),
            },
            db_path=self.db_path,
        )

        print(
            "Kalshi BTC Quant System — Paper Trade Lifecycle"
        )
        print(f"Product:          {self.product_id}")
        print(f"Database:         {self.db_path}")
        print(
            "Live bars:        "
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
        print(
            "Paper trading:    "
            + (
                f"ENABLED for {self.paper_engine.market_ticker}"
                if self.paper_engine.enabled
                else "DISABLED — configure KALSHI_MARKET_TICKER"
            )
        )
        print(
            "Settlement check: "
            f"every {self.settlement_check_seconds:g} seconds"
        )
        print("No live-order method is used by this recorder.")
        print("Press Control+C to stop.\n")

        try:
            await stream_trades(
                product_id=self.product_id,
                callback=self.on_trade,
            )
        finally:
            await self._maybe_settle_paper_trades(force=True)
            flushed_bars = self.bar_builder.flush()
            signal_stats = self.signal_pipeline.stats()

            log_event(
                level="INFO",
                component="coinbase_recorder",
                message=(
                    "Coinbase bars, signals, and paper lifecycle "
                    "pipeline stopped"
                ),
                details={
                    "session_trades": self.session_count,
                    "total_trades": trade_count(self.db_path),
                    "flushed_partial_bars": len(flushed_bars),
                    "signals_generated": signal_stats.generated,
                    "paper_evaluated": self.paper_engine.evaluated_count,
                    "paper_opened": self.paper_engine.opened_count,
                    "paper_skipped": self.paper_engine.skipped_count,
                    "paper_blocked": self.paper_engine.blocked_count,
                    "paper_duplicates": self.paper_engine.duplicate_count,
                    "settlement_markets_checked": (
                        self.settlement_engine.checked_market_count
                    ),
                    "paper_settled": (
                        self.settlement_engine.settled_count
                    ),
                    "paper_settlement_pending": (
                        self.settlement_engine.pending_count
                    ),
                    "paper_settlement_errors": (
                        self.settlement_engine.error_count
                    ),
                },
                db_path=self.db_path,
            )

            print(
                "\nSaved "
                f"{len(flushed_bars)} active partial bars before shutdown."
            )
            print(
                "Automatic signals created this session: "
                f"{signal_stats.generated:,}"
            )
            print(
                "Simulated paper trades opened this session: "
                f"{self.paper_engine.opened_count:,}"
            )
            print(
                "Paper trades settled this session: "
                f"{self.settlement_engine.settled_count:,}"
            )


async def main() -> None:
    recorder = CoinbaseTradeRecorder()
    await recorder.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nRecorder stopped safely.")
