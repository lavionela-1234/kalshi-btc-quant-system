from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from kalshi_quant.config import Settings
from kalshi_quant.kalshi import Book
from kalshi_quant.market_signal import MarketSignal
from kalshi_quant.paper_trade_store import paper_trade_summary
from kalshi_quant.paper_trading_engine import PaperTradingEngine


class FakeRest:
    def __init__(self) -> None:
        self.market_calls = 0
        self.orderbook_calls = 0

    def market(self, ticker: str) -> dict:
        self.market_calls += 1
        return {
            "ticker": ticker,
            "title": "BTC above target",
            "close_time": (
                datetime.now(timezone.utc)
                + timedelta(seconds=120)
            ).isoformat(),
            "status": "open",
        }

    def orderbook(self, ticker: str, depth: int = 0) -> Book:
        self.orderbook_calls += 1
        book = Book()
        book.apply_snapshot(
            {
                "yes": [[53, 100]],
                "no": [[45, 100]],
            }
        )
        return book


def make_settings(**overrides) -> Settings:
    values = {
        "paper_mode": True,
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


def bullish_signal() -> MarketSignal:
    return MarketSignal(
        timestamp="2026-07-29T12:00:00+00:00",
        direction="BULLISH",
        action="LONG_BIAS",
        score=45.0,
        probability_up=0.80,
        confidence=0.70,
        volatility_regime="NORMAL",
        trend_score=20.0,
        momentum_score=10.0,
        vwap_score=8.0,
        rsi_score=7.0,
        order_flow_score=0.0,
        order_flow_imbalance=0.0,
        order_flow_reliability=1.0,
        timeframe_confirmation="BULLISH",
        timeframe_agreement=1.0,
        reason="Test bullish signal",
    )


def test_engine_opens_simulated_yes_trade(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "engine.db"
    rest = FakeRest()
    engine = PaperTradingEngine(
        settings=make_settings(),
        rest_client=rest,
        db_path=db_path,
    )

    outcome = engine.process_signal(
        signal=bullish_signal(),
        btc_price=64000.0,
    )

    assert outcome.decision == "OPEN"
    assert outcome.side == "YES"
    assert outcome.contracts > 0
    assert outcome.stake <= 20.01
    assert outcome.paper_trade_id is not None

    summary = paper_trade_summary(db_path)
    assert summary["total_trades"] == 1
    assert engine.opened_count == 1


def test_engine_prevents_duplicate_signal(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "duplicate.db"
    engine = PaperTradingEngine(
        settings=make_settings(),
        rest_client=FakeRest(),
        db_path=db_path,
    )

    first = engine.process_signal(
        signal=bullish_signal(),
        btc_price=64000.0,
    )
    second = engine.process_signal(
        signal=bullish_signal(),
        btc_price=64000.0,
    )

    assert first.decision == "OPEN"
    assert second.decision == "DUPLICATE"
    assert paper_trade_summary(db_path)["total_trades"] == 1


def test_engine_is_blocked_when_paper_mode_is_off(
    tmp_path: Path,
) -> None:
    rest = FakeRest()
    engine = PaperTradingEngine(
        settings=make_settings(paper_mode=False),
        rest_client=rest,
        db_path=tmp_path / "off.db",
    )

    outcome = engine.process_signal(
        signal=bullish_signal(),
        btc_price=64000.0,
    )

    assert outcome.decision == "BLOCKED"
    assert rest.market_calls == 0
    assert rest.orderbook_calls == 0
