from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .config import Settings
from .db import DEFAULT_DB_PATH
from .features import FeatureSnapshot
from .kalshi import Book, KalshiREST
from .market_signal import MarketSignal
from .paper_trade_store import (
    PaperDecisionRecord,
    paper_decision_exists,
    realized_pnl_today,
    save_paper_decision,
)
from .risk import fractional_kelly
from .signal import evaluate_signal


class KalshiMarketClient(Protocol):
    def market(self, ticker: str) -> dict[str, Any]:
        ...

    def orderbook(self, ticker: str, depth: int = 0) -> Book:
        ...


@dataclass(frozen=True)
class PaperTradeOutcome:
    decision: str
    side: str | None
    edge: float
    contracts: int
    stake: float
    reason: str
    paper_trade_id: int | None = None


class PaperTradingEngine:
    """Evaluate technical signals and create simulated trades only."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        rest_client: KalshiMarketClient | None = None,
        db_path: str | Path = DEFAULT_DB_PATH,
    ) -> None:
        self.settings = settings or Settings()
        self.db_path = Path(db_path)
        self.market_ticker = (
            self.settings.kalshi_market_ticker.strip()
        )
        self.rest = (
            rest_client
            if rest_client is not None
            else KalshiREST(self.settings)
        )

        self.evaluated_count = 0
        self.opened_count = 0
        self.skipped_count = 0
        self.blocked_count = 0
        self.duplicate_count = 0

    @property
    def enabled(self) -> bool:
        return (
            self.settings.paper_mode
            and bool(self.market_ticker)
        )

    @staticmethod
    def _parse_time(value: str) -> datetime:
        normalized = str(value).replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(normalized)

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        return timestamp.astimezone(timezone.utc)

    def _target_price(self, market: dict[str, Any]) -> float:
        if self.settings.kalshi_target_price > 0:
            return self.settings.kalshi_target_price

        for key in (
            "target_price",
            "strike",
            "floor_strike",
            "cap_strike",
        ):
            value = market.get(key)

            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue

            if parsed > 0:
                return parsed

        raise ValueError(
            "No Kalshi target price was configured or found "
            "in the market response"
        )

    def _market_times(
        self,
        market: dict[str, Any],
    ) -> tuple[datetime, float]:
        close_raw = (
            market.get("close_time")
            or market.get("expected_expiration_time")
        )

        if not close_raw:
            raise ValueError(
                "Kalshi market response did not include a close time"
            )

        close_time = self._parse_time(str(close_raw))
        seconds_remaining = max(
            (
                close_time
                - datetime.now(timezone.utc)
            ).total_seconds(),
            0.0,
        )

        return close_time, seconds_remaining

    @staticmethod
    def _spread(book: Book) -> float | None:
        if book.yes_ask is None or book.no_ask is None:
            return None

        return book.yes_ask - (1 - book.no_ask)

    def _feature_snapshot(
        self,
        *,
        signal: MarketSignal,
        btc_price: float,
        target_price: float,
        close_time: datetime,
        book: Book,
    ) -> FeatureSnapshot:
        now = datetime.now(timezone.utc)

        return FeatureSnapshot(
            btc_price=btc_price,
            target_price=target_price,
            distance_usd=btc_price - target_price,
            distance_bps=(
                (btc_price - target_price)
                / target_price
                * 10000
            ),
            seconds_remaining=max(
                (close_time - now).total_seconds(),
                0.0,
            ),
            ret_5s=0.0,
            ret_15s=0.0,
            ret_60s=0.0,
            rv_60s=0.0,
            rv_300s=0.0,
            trend_ema=signal.trend_score / 100.0,
            momentum=signal.momentum_score / 100.0,
            orderbook_imbalance=book.imbalance(),
        )

    def _save_outcome(
        self,
        *,
        signal: MarketSignal,
        market: dict[str, Any],
        btc_price: float,
        target_price: float,
        seconds_remaining: float,
        book: Book,
        outcome: PaperTradeOutcome,
    ) -> PaperTradeOutcome:
        saved = save_paper_decision(
            PaperDecisionRecord(
                market_ticker=self.market_ticker,
                signal_timestamp=str(signal.timestamp),
                technical_direction=signal.direction,
                technical_action=signal.action,
                technical_score=signal.score,
                technical_probability_up=signal.probability_up,
                technical_confidence=signal.confidence,
                btc_price=btc_price,
                target_price=target_price,
                seconds_remaining=seconds_remaining,
                yes_bid=book.yes_bid,
                yes_ask=book.yes_ask,
                no_bid=book.no_bid,
                no_ask=book.no_ask,
                spread=self._spread(book),
                decision=outcome.decision,
                side=outcome.side,
                edge=outcome.edge,
                contracts=outcome.contracts,
                stake=outcome.stake,
                reason=outcome.reason,
            ),
            market=market,
            db_path=self.db_path,
        )

        if not saved.created:
            self.duplicate_count += 1
            return PaperTradeOutcome(
                decision="DUPLICATE",
                side=outcome.side,
                edge=outcome.edge,
                contracts=0,
                stake=0.0,
                reason="Decision already stored for this signal",
                paper_trade_id=saved.paper_trade_id,
            )

        return PaperTradeOutcome(
            decision=outcome.decision,
            side=outcome.side,
            edge=outcome.edge,
            contracts=outcome.contracts,
            stake=outcome.stake,
            reason=outcome.reason,
            paper_trade_id=saved.paper_trade_id,
        )

    def process_signal(
        self,
        *,
        signal: MarketSignal,
        btc_price: float,
    ) -> PaperTradeOutcome:
        if not self.settings.paper_mode:
            self.blocked_count += 1
            return PaperTradeOutcome(
                "BLOCKED",
                None,
                0.0,
                0,
                0.0,
                "PAPER_MODE is disabled",
            )

        if not self.market_ticker:
            self.skipped_count += 1
            return PaperTradeOutcome(
                "SKIP",
                None,
                0.0,
                0,
                0.0,
                "KALSHI_MARKET_TICKER is not configured",
            )

        if signal.timestamp is None:
            self.blocked_count += 1
            return PaperTradeOutcome(
                "BLOCKED",
                None,
                0.0,
                0,
                0.0,
                "Technical signal has no timestamp",
            )

        if paper_decision_exists(
            market_ticker=self.market_ticker,
            signal_timestamp=str(signal.timestamp),
            db_path=self.db_path,
        ):
            self.duplicate_count += 1
            return PaperTradeOutcome(
                "DUPLICATE",
                None,
                0.0,
                0,
                0.0,
                "Decision already stored for this signal",
            )

        market = self.rest.market(self.market_ticker)
        book = self.rest.orderbook(self.market_ticker)
        target_price = self._target_price(market)
        close_time, seconds_remaining = self._market_times(
            market
        )

        self.evaluated_count += 1

        if signal.action == "NO_TRADE":
            self.skipped_count += 1
            return self._save_outcome(
                signal=signal,
                market=market,
                btc_price=btc_price,
                target_price=target_price,
                seconds_remaining=seconds_remaining,
                book=book,
                outcome=PaperTradeOutcome(
                    "SKIP",
                    None,
                    0.0,
                    0,
                    0.0,
                    "Technical signal action is NO_TRADE",
                ),
            )

        if (
            signal.confidence
            < self.settings.paper_min_confidence
        ):
            self.skipped_count += 1
            return self._save_outcome(
                signal=signal,
                market=market,
                btc_price=btc_price,
                target_price=target_price,
                seconds_remaining=seconds_remaining,
                book=book,
                outcome=PaperTradeOutcome(
                    "SKIP",
                    None,
                    0.0,
                    0,
                    0.0,
                    "Technical confidence is below the paper threshold",
                ),
            )

        features = self._feature_snapshot(
            signal=signal,
            btc_price=btc_price,
            target_price=target_price,
            close_time=close_time,
            book=book,
        )

        edge_signal = evaluate_signal(
            features,
            signal.probability_up,
            book.yes_ask,
            book.no_ask,
            self.settings.min_edge,
            self.settings.cost_buffer,
            max_spread=self.settings.paper_max_spread,
            min_seconds=self.settings.paper_min_seconds,
            max_seconds=self.settings.paper_max_seconds,
        )

        expected_side = (
            "YES"
            if signal.action == "LONG_BIAS"
            else "NO"
            if signal.action == "SHORT_BIAS"
            else None
        )

        if edge_signal.action != "FLAG":
            self.skipped_count += 1
            return self._save_outcome(
                signal=signal,
                market=market,
                btc_price=btc_price,
                target_price=target_price,
                seconds_remaining=seconds_remaining,
                book=book,
                outcome=PaperTradeOutcome(
                    "SKIP",
                    None,
                    edge_signal.edge,
                    0,
                    0.0,
                    edge_signal.reason,
                ),
            )

        if edge_signal.side != expected_side:
            self.skipped_count += 1
            return self._save_outcome(
                signal=signal,
                market=market,
                btc_price=btc_price,
                target_price=target_price,
                seconds_remaining=seconds_remaining,
                book=book,
                outcome=PaperTradeOutcome(
                    "SKIP",
                    edge_signal.side,
                    edge_signal.edge,
                    0,
                    0.0,
                    "Kalshi edge side conflicts with technical direction",
                ),
            )

        daily_pnl = realized_pnl_today(self.db_path)
        daily_loss_limit = (
            self.settings.paper_bankroll
            * self.settings.daily_loss_limit_fraction
        )

        if daily_pnl <= -daily_loss_limit:
            self.blocked_count += 1
            return self._save_outcome(
                signal=signal,
                market=market,
                btc_price=btc_price,
                target_price=target_price,
                seconds_remaining=seconds_remaining,
                book=book,
                outcome=PaperTradeOutcome(
                    "BLOCKED",
                    edge_signal.side,
                    edge_signal.edge,
                    0,
                    0.0,
                    "Daily paper loss limit reached",
                ),
            )

        contract_price = (
            book.yes_ask
            if edge_signal.side == "YES"
            else book.no_ask
        )
        side_probability = (
            signal.probability_up
            if edge_signal.side == "YES"
            else 1 - signal.probability_up
        )

        sizing = fractional_kelly(
            self.settings.paper_bankroll,
            side_probability,
            float(contract_price),
            self.settings.kelly_fraction,
            self.settings.max_position_fraction,
        )

        if sizing.blocked:
            self.blocked_count += 1
            return self._save_outcome(
                signal=signal,
                market=market,
                btc_price=btc_price,
                target_price=target_price,
                seconds_remaining=seconds_remaining,
                book=book,
                outcome=PaperTradeOutcome(
                    "BLOCKED",
                    edge_signal.side,
                    edge_signal.edge,
                    0,
                    0.0,
                    sizing.reason,
                ),
            )

        self.opened_count += 1

        return self._save_outcome(
            signal=signal,
            market=market,
            btc_price=btc_price,
            target_price=target_price,
            seconds_remaining=seconds_remaining,
            book=book,
            outcome=PaperTradeOutcome(
                "OPEN",
                edge_signal.side,
                edge_signal.edge,
                sizing.contracts,
                sizing.stake_dollars,
                "Simulated paper trade opened",
            ),
        )
