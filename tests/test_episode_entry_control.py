from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from kalshi_quant.config import Settings
from kalshi_quant.db import database_connection
from kalshi_quant.kalshi import Book
from kalshi_quant.market_signal import MarketSignal
from kalshi_quant.paper_trade_store import paper_trade_summary
from kalshi_quant.paper_trading_engine import PaperTradingEngine


class FakeRest:
    def market(self, ticker: str) -> dict:
        return {
            "ticker": ticker,
            "title": "BTC above target",
            "close_time": (
                datetime.now(timezone.utc)
                + timedelta(seconds=120)
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
                "yes": [[53, 100]],
                "no": [[45, 100]],
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
        "paper_episode_gap_seconds": 15.0,
        "paper_reentry_cooldown_seconds": 30.0,
        "min_edge": 0.02,
        "cost_buffer": 0.01,
        "kelly_fraction": 0.25,
        "max_position_fraction": 0.02,
        "daily_loss_limit_fraction": 0.05,
    }
    values.update(overrides)
    return Settings(**values)


def bullish_signal(timestamp: datetime) -> MarketSignal:
    return MarketSignal(
        timestamp=timestamp.isoformat(),
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
        reason="Episode-control test signal",
    )


def close_trade(
    *,
    db_path: Path,
    paper_trade_id: int,
    closed_at: datetime,
) -> None:
    with database_connection(db_path) as connection:
        connection.execute(
            """
            UPDATE paper_trades
            SET
                status = 'CLOSED',
                closed_at = ?,
                won = 1,
                pnl = 1.0
            WHERE id = ?
            """,
            (
                closed_at.isoformat(),
                paper_trade_id,
            ),
        )


def make_engine(
    *,
    db_path: Path,
    settings: Settings | None = None,
) -> PaperTradingEngine:
    return PaperTradingEngine(
        settings=settings or make_settings(),
        rest_client=FakeRest(),
        db_path=db_path,
    )


def test_open_position_blocks_repeated_entry_after_restart(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "open-position.db"
    start = datetime(
        2026,
        7,
        31,
        12,
        0,
        0,
        tzinfo=timezone.utc,
    )

    first_engine = make_engine(db_path=db_path)
    first = first_engine.process_signal(
        signal=bullish_signal(start),
        btc_price=64000.0,
    )

    restarted_engine = make_engine(db_path=db_path)
    second = restarted_engine.process_signal(
        signal=bullish_signal(
            start + timedelta(seconds=5)
        ),
        btc_price=64000.0,
    )

    assert first.decision == "OPEN"
    assert second.decision == "BLOCKED"
    assert second.reason == "OPEN_POSITION"
    assert second.contracts == 0
    assert paper_trade_summary(db_path)["total_trades"] == 1


def test_active_episode_blocks_entry_after_trade_closes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "active-episode.db"
    start = datetime(
        2026,
        7,
        31,
        12,
        5,
        0,
        tzinfo=timezone.utc,
    )
    settings = make_settings(
        paper_reentry_cooldown_seconds=0.0
    )

    first_engine = make_engine(
        db_path=db_path,
        settings=settings,
    )
    first = first_engine.process_signal(
        signal=bullish_signal(start),
        btc_price=64000.0,
    )

    assert first.paper_trade_id is not None

    close_trade(
        db_path=db_path,
        paper_trade_id=first.paper_trade_id,
        closed_at=start + timedelta(seconds=1),
    )

    restarted_engine = make_engine(
        db_path=db_path,
        settings=settings,
    )
    second = restarted_engine.process_signal(
        signal=bullish_signal(
            start + timedelta(seconds=5)
        ),
        btc_price=64000.0,
    )

    assert first.decision == "OPEN"
    assert second.decision == "BLOCKED"
    assert second.reason == "ACTIVE_EPISODE"
    assert paper_trade_summary(db_path)["total_trades"] == 1


def test_cooldown_blocks_entry_after_episode_gap(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "cooldown.db"
    start = datetime(
        2026,
        7,
        31,
        12,
        10,
        0,
        tzinfo=timezone.utc,
    )
    settings = make_settings(
        paper_episode_gap_seconds=15.0,
        paper_reentry_cooldown_seconds=30.0,
    )

    engine = make_engine(
        db_path=db_path,
        settings=settings,
    )
    first = engine.process_signal(
        signal=bullish_signal(start),
        btc_price=64000.0,
    )

    assert first.paper_trade_id is not None

    close_trade(
        db_path=db_path,
        paper_trade_id=first.paper_trade_id,
        closed_at=start + timedelta(seconds=10),
    )

    second = engine.process_signal(
        signal=bullish_signal(
            start + timedelta(seconds=20)
        ),
        btc_price=64000.0,
    )

    assert second.decision == "BLOCKED"
    assert second.reason == "COOLDOWN"
    assert paper_trade_summary(db_path)["total_trades"] == 1


def test_reentry_allowed_after_episode_and_cooldown_end(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "reentry.db"
    start = datetime(
        2026,
        7,
        31,
        12,
        15,
        0,
        tzinfo=timezone.utc,
    )
    settings = make_settings(
        paper_episode_gap_seconds=15.0,
        paper_reentry_cooldown_seconds=30.0,
    )

    first_engine = make_engine(
        db_path=db_path,
        settings=settings,
    )
    first = first_engine.process_signal(
        signal=bullish_signal(start),
        btc_price=64000.0,
    )

    assert first.paper_trade_id is not None

    close_trade(
        db_path=db_path,
        paper_trade_id=first.paper_trade_id,
        closed_at=start + timedelta(seconds=5),
    )

    restarted_engine = make_engine(
        db_path=db_path,
        settings=settings,
    )
    second = restarted_engine.process_signal(
        signal=bullish_signal(
            start + timedelta(seconds=40)
        ),
        btc_price=64000.0,
    )

    assert first.decision == "OPEN"
    assert second.decision == "OPEN"
    assert second.paper_trade_id is not None
    assert second.paper_trade_id != first.paper_trade_id
    assert paper_trade_summary(db_path)["total_trades"] == 2
