from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from kalshi_quant.config import Settings
from kalshi_quant.kalshi import Book
from kalshi_quant.market_signal import MarketSignal
from kalshi_quant.paper_trading_engine import PaperTradingEngine


class ConfigurableRest:
    def __init__(
        self,
        *,
        seconds_remaining: float = 120.0,
        yes_levels: list[list[int]] | None = None,
        no_levels: list[list[int]] | None = None,
    ) -> None:
        self.seconds_remaining = seconds_remaining
        self.yes_levels = (
            [[53, 100]]
            if yes_levels is None
            else yes_levels
        )
        self.no_levels = (
            [[45, 100]]
            if no_levels is None
            else no_levels
        )

    def market(self, ticker: str) -> dict:
        return {
            "ticker": ticker,
            "title": "BTC above target",
            "close_time": (
                datetime.now(timezone.utc)
                + timedelta(seconds=self.seconds_remaining)
            ).isoformat(),
            "status": "open",
        }

    def orderbook(
        self,
        ticker: str,
        depth: int = 0,
    ) -> Book:
        book = Book()
        book.apply_snapshot(
            {
                "yes": self.yes_levels,
                "no": self.no_levels,
            }
        )
        return book


def make_settings(**overrides) -> Settings:
    values = {
        "paper_mode": True,
        "kalshi_auto_discovery": False,
        "kalshi_market_ticker": "TEST-BTC",
        "kalshi_target_price": 63900.0,
        "paper_bankroll": 1000.0,
        "paper_min_confidence": 0.25,
        "paper_min_seconds": 10.0,
        "paper_max_seconds": 300.0,
        "paper_max_spread": 0.08,
        "min_edge": 0.02,
        "cost_buffer": 0.01,
        "kelly_fraction": 0.25,
        "max_position_fraction": 0.02,
        "daily_loss_limit_fraction": 0.05,
    }
    values.update(overrides)
    return Settings(**values)


def make_signal(**overrides) -> MarketSignal:
    values = {
        "timestamp": "2026-07-31T12:00:00+00:00",
        "direction": "BULLISH",
        "action": "LONG_BIAS",
        "score": 45.0,
        "probability_up": 0.80,
        "confidence": 0.70,
        "volatility_regime": "NORMAL",
        "trend_score": 20.0,
        "momentum_score": 10.0,
        "vwap_score": 8.0,
        "rsi_score": 7.0,
        "order_flow_score": 0.0,
        "order_flow_imbalance": 0.0,
        "order_flow_reliability": 1.0,
        "timeframe_confirmation": "AGREE",
        "timeframe_agreement": 1.0,
        "reason": "Calibration test signal",
    }
    values.update(overrides)
    return MarketSignal(**values)


def run_engine(
    tmp_path: Path,
    *,
    signal: MarketSignal | None = None,
    rest: ConfigurableRest | None = None,
    settings: Settings | None = None,
):
    engine = PaperTradingEngine(
        settings=settings or make_settings(),
        rest_client=rest or ConfigurableRest(),
        db_path=tmp_path / "calibration.db",
    )
    outcome = engine.process_signal(
        signal=signal or make_signal(),
        btc_price=64000.0,
    )
    return outcome, engine


def test_no_trade_action_is_skipped(
    tmp_path: Path,
) -> None:
    outcome, engine = run_engine(
        tmp_path,
        signal=make_signal(
            action="NO_TRADE",
            score=15.0,
            confidence=0.20,
        ),
    )

    assert outcome.decision == "SKIP"
    assert outcome.reason == "Technical signal action is NO_TRADE"
    assert engine.opened_count == 0


def test_low_confidence_is_skipped(
    tmp_path: Path,
) -> None:
    outcome, engine = run_engine(
        tmp_path,
        signal=make_signal(confidence=0.20),
    )

    assert outcome.decision == "SKIP"
    assert (
        outcome.reason
        == "Technical confidence is below the paper threshold"
    )
    assert engine.opened_count == 0


def test_incomplete_orderbook_is_skipped(
    tmp_path: Path,
) -> None:
    outcome, engine = run_engine(
        tmp_path,
        rest=ConfigurableRest(
            yes_levels=[],
            no_levels=[],
        ),
    )

    assert outcome.decision == "SKIP"
    assert outcome.reason == "Incomplete order book"
    assert engine.opened_count == 0


def test_wide_spread_is_skipped(
    tmp_path: Path,
) -> None:
    outcome, engine = run_engine(
        tmp_path,
        rest=ConfigurableRest(
            yes_levels=[[40, 100]],
            no_levels=[[40, 100]],
        ),
    )

    assert outcome.decision == "SKIP"
    assert outcome.reason == "Spread too wide"
    assert engine.opened_count == 0


def test_outside_time_window_is_skipped(
    tmp_path: Path,
) -> None:
    outcome, engine = run_engine(
        tmp_path,
        rest=ConfigurableRest(seconds_remaining=600.0),
    )

    assert outcome.decision == "SKIP"
    assert outcome.reason == "Outside time window"
    assert engine.opened_count == 0


def test_insufficient_edge_is_skipped(
    tmp_path: Path,
) -> None:
    outcome, engine = run_engine(
        tmp_path,
        signal=make_signal(probability_up=0.56),
    )

    assert outcome.decision == "SKIP"
    assert outcome.reason == "Insufficient edge"
    assert engine.opened_count == 0


def test_direction_conflict_is_skipped(
    tmp_path: Path,
) -> None:
    outcome, engine = run_engine(
        tmp_path,
        signal=make_signal(
            action="LONG_BIAS",
            probability_up=0.20,
        ),
    )

    assert outcome.decision == "SKIP"
    assert outcome.side == "NO"
    assert (
        outcome.reason
        == "Kalshi edge side conflicts with technical direction"
    )
    assert engine.opened_count == 0


def test_engine_opens_simulated_no_trade(
    tmp_path: Path,
) -> None:
    outcome, engine = run_engine(
        tmp_path,
        signal=make_signal(
            direction="BEARISH",
            action="SHORT_BIAS",
            score=-45.0,
            probability_up=0.20,
            timeframe_confirmation="AGREE",
        ),
    )

    assert outcome.decision == "OPEN"
    assert outcome.side == "NO"
    assert outcome.edge >= 0.02
    assert outcome.contracts > 0
    assert outcome.stake <= 20.01
    assert outcome.paper_trade_id is not None
    assert engine.opened_count == 1


def test_kelly_sizing_blocks_zero_contract_position(
    tmp_path: Path,
) -> None:
    outcome, engine = run_engine(
        tmp_path,
        settings=make_settings(paper_bankroll=0.10),
    )

    assert outcome.decision == "BLOCKED"
    assert outcome.reason == "No positive Kelly stake"
    assert outcome.contracts == 0
    assert engine.opened_count == 0
