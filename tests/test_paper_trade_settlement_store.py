from __future__ import annotations

from pathlib import Path

import pytest

from kalshi_quant.paper_trade_lifecycle import (
    paper_bankroll_history,
    paper_trade_summary,
    recent_paper_trades,
    settle_paper_trade,
)
from kalshi_quant.paper_trade_store import (
    PaperDecisionRecord,
    save_paper_decision,
)


def create_trade(
    db_path: Path,
    *,
    ticker: str,
    timestamp: str,
    side: str,
    entry_price: float,
    contracts: int,
) -> int:
    record = PaperDecisionRecord(
        market_ticker=ticker,
        signal_timestamp=timestamp,
        technical_direction=(
            "BULLISH" if side == "YES" else "BEARISH"
        ),
        technical_action=(
            "LONG_BIAS" if side == "YES" else "SHORT_BIAS"
        ),
        technical_score=45.0 if side == "YES" else -45.0,
        technical_probability_up=0.80,
        technical_confidence=0.70,
        btc_price=64000.0,
        target_price=63900.0,
        seconds_remaining=120.0,
        yes_bid=0.53,
        yes_ask=entry_price if side == "YES" else 0.55,
        no_bid=0.45,
        no_ask=entry_price if side == "NO" else 0.47,
        spread=0.02,
        decision="OPEN",
        side=side,
        edge=0.20,
        contracts=contracts,
        stake=entry_price * contracts,
        reason="Simulated paper trade opened",
    )
    saved = save_paper_decision(
        record,
        market={
            "ticker": ticker,
            "title": ticker,
            "status": "active",
            "close_time": "2026-07-30T12:02:00Z",
        },
        db_path=db_path,
    )
    assert saved.paper_trade_id is not None
    return saved.paper_trade_id


def test_settle_winner_and_prevent_duplicate(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "settle.db"
    trade_id = create_trade(
        db_path,
        ticker="TEST-YES",
        timestamp="2026-07-30T12:00:00+00:00",
        side="YES",
        entry_price=0.55,
        contracts=20,
    )

    first = settle_paper_trade(
        paper_trade_id=trade_id,
        market_result="yes",
        starting_bankroll=1000.0,
        db_path=db_path,
    )
    second = settle_paper_trade(
        paper_trade_id=trade_id,
        market_result="yes",
        starting_bankroll=1000.0,
        db_path=db_path,
    )

    assert first.created is True
    assert first.won is True
    assert first.pnl == pytest.approx(9.0)
    assert first.bankroll_after == pytest.approx(1009.0)
    assert first.drawdown == pytest.approx(0.0)

    assert second.created is False
    assert second.settlement_id == first.settlement_id

    trades = recent_paper_trades(db_path=db_path)
    assert trades[0]["status"] == "CLOSED"
    assert trades[0]["won"] == 1
    assert trades[0]["pnl"] == pytest.approx(9.0)


def test_bankroll_and_drawdown_follow_settlement_order(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "drawdown.db"

    winner_id = create_trade(
        db_path,
        ticker="TEST-WIN",
        timestamp="2026-07-30T12:00:00+00:00",
        side="YES",
        entry_price=0.55,
        contracts=20,
    )
    loser_id = create_trade(
        db_path,
        ticker="TEST-LOSS",
        timestamp="2026-07-30T12:01:00+00:00",
        side="NO",
        entry_price=0.47,
        contracts=20,
    )

    win = settle_paper_trade(
        paper_trade_id=winner_id,
        market_result="YES",
        starting_bankroll=1000.0,
        settled_at="2026-07-30T12:03:00+00:00",
        db_path=db_path,
    )
    loss = settle_paper_trade(
        paper_trade_id=loser_id,
        market_result="YES",
        starting_bankroll=1000.0,
        settled_at="2026-07-30T12:04:00+00:00",
        db_path=db_path,
    )

    assert win.pnl == pytest.approx(9.0)
    assert loss.pnl == pytest.approx(-9.4)
    assert loss.bankroll_before == pytest.approx(1009.0)
    assert loss.bankroll_after == pytest.approx(999.6)
    assert loss.peak_bankroll == pytest.approx(1009.0)

    summary = paper_trade_summary(
        db_path,
        starting_bankroll=1000.0,
    )
    assert summary["closed_trades"] == 2
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["win_rate"] == pytest.approx(0.5)
    assert summary["realized_pnl"] == pytest.approx(-0.4)
    assert summary["current_bankroll"] == pytest.approx(999.6)
    assert summary["max_drawdown"] == pytest.approx(
        loss.drawdown
    )

    history = paper_bankroll_history(db_path=db_path)
    assert len(history) == 2
    assert history[-1]["bankroll_after"] == pytest.approx(
        999.6
    )
