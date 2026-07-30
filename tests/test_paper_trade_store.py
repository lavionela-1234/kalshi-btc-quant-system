from __future__ import annotations

from pathlib import Path

from kalshi_quant.paper_trade_store import (
    PaperDecisionRecord,
    paper_decision_exists,
    paper_trade_summary,
    recent_paper_decisions,
    recent_paper_trades,
    save_paper_decision,
)


def make_record() -> PaperDecisionRecord:
    return PaperDecisionRecord(
        market_ticker="TEST-BTC",
        signal_timestamp="2026-07-29T12:00:00+00:00",
        technical_direction="BULLISH",
        technical_action="LONG_BIAS",
        technical_score=45.0,
        technical_probability_up=0.80,
        technical_confidence=0.70,
        btc_price=64000.0,
        target_price=63900.0,
        seconds_remaining=120.0,
        yes_bid=0.53,
        yes_ask=0.55,
        no_bid=0.45,
        no_ask=0.47,
        spread=0.02,
        decision="OPEN",
        side="YES",
        edge=0.24,
        contracts=36,
        stake=19.80,
        reason="Simulated paper trade opened",
    )


def market() -> dict:
    return {
        "ticker": "TEST-BTC",
        "title": "Test BTC market",
        "close_time": "2026-07-29T12:02:00Z",
        "status": "open",
    }


def test_save_open_decision_creates_trade(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "paper.db"

    result = save_paper_decision(
        make_record(),
        market=market(),
        db_path=db_path,
    )

    assert result.created is True
    assert result.paper_trade_id is not None
    assert paper_decision_exists(
        market_ticker="TEST-BTC",
        signal_timestamp=make_record().signal_timestamp,
        db_path=db_path,
    )

    summary = paper_trade_summary(db_path)
    assert summary["total_trades"] == 1
    assert summary["open_trades"] == 1
    assert summary["total_decisions"] == 1

    trades = recent_paper_trades(db_path=db_path)
    assert trades[0]["side"] == "YES"
    assert trades[0]["contracts"] == 36


def test_duplicate_decision_does_not_duplicate_trade(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "duplicate.db"

    first = save_paper_decision(
        make_record(),
        market=market(),
        db_path=db_path,
    )
    second = save_paper_decision(
        make_record(),
        market=market(),
        db_path=db_path,
    )

    assert first.created is True
    assert second.created is False
    assert len(recent_paper_decisions(db_path=db_path)) == 1
    assert len(recent_paper_trades(db_path=db_path)) == 1
