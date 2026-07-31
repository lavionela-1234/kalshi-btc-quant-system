from __future__ import annotations

from pathlib import Path

from kalshi_quant.dashboard_data import (
    paper_entry_diagnostics as dashboard_entry_diagnostics,
)
from kalshi_quant.paper_trade_store import (
    PaperDecisionRecord,
    paper_entry_diagnostics,
    save_paper_decision,
)


def market() -> dict:
    return {
        "ticker": "TEST-BTC",
        "title": "Test BTC market",
        "close_time": "2026-07-31T12:05:00Z",
        "status": "open",
    }


def make_record(
    minute: int,
    **overrides,
) -> PaperDecisionRecord:
    values = {
        "market_ticker": "TEST-BTC",
        "signal_timestamp": (
            f"2026-07-31T12:{minute:02d}:00+00:00"
        ),
        "technical_direction": "BULLISH",
        "technical_action": "LONG_BIAS",
        "technical_score": 45.0,
        "technical_probability_up": 0.80,
        "technical_confidence": 0.70,
        "btc_price": 64000.0,
        "target_price": 63900.0,
        "seconds_remaining": 120.0,
        "yes_bid": 0.53,
        "yes_ask": 0.55,
        "no_bid": 0.45,
        "no_ask": 0.47,
        "spread": 0.02,
        "decision": "SKIP",
        "side": None,
        "edge": 0.0,
        "contracts": 0,
        "stake": 0.0,
        "reason": "Test decision",
    }
    values.update(overrides)
    return PaperDecisionRecord(**values)


def save(
    db_path: Path,
    minute: int,
    **overrides,
) -> None:
    result = save_paper_decision(
        make_record(minute, **overrides),
        market=market(),
        db_path=db_path,
    )
    assert result.created is True


def test_entry_diagnostics_follow_sequential_gates(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "diagnostics.db"

    save(
        db_path,
        1,
        technical_action="NO_TRADE",
        technical_score=10.0,
        technical_confidence=0.10,
        reason="Technical signal action is NO_TRADE",
    )
    save(
        db_path,
        2,
        technical_confidence=0.20,
        reason="Technical confidence is below the paper threshold",
    )
    save(
        db_path,
        3,
        yes_ask=None,
        no_ask=None,
        spread=None,
        reason="Incomplete order book",
    )
    save(
        db_path,
        4,
        spread=0.20,
        reason="Spread too wide",
    )
    save(
        db_path,
        5,
        seconds_remaining=600.0,
        reason="Outside time window",
    )
    save(
        db_path,
        6,
        edge=0.01,
        reason="Insufficient edge",
    )
    save(
        db_path,
        7,
        side="NO",
        edge=0.20,
        reason=(
            "Kalshi edge side conflicts with technical direction"
        ),
    )
    save(
        db_path,
        8,
        decision="BLOCKED",
        side="YES",
        edge=0.20,
        reason="No positive Kelly stake",
    )
    save(
        db_path,
        9,
        decision="OPEN",
        side="YES",
        edge=0.20,
        contracts=10,
        stake=5.50,
        reason="Simulated paper trade opened",
    )

    diagnostics = paper_entry_diagnostics(db_path)

    expected = [
        ("Technical action", 9, 8, 1),
        ("Confidence", 8, 7, 1),
        ("Order book", 7, 6, 1),
        ("Spread", 6, 5, 1),
        ("Time window", 5, 4, 1),
        ("Expected edge", 4, 3, 1),
        ("Direction alignment", 3, 2, 1),
        ("Risk controls", 2, 1, 1),
    ]

    assert [
        (
            row["gate"],
            row["evaluated"],
            row["passed"],
            row["failed"],
        )
        for row in diagnostics
    ] == expected

    assert diagnostics[0]["pass_rate"] == 8 / 9
    assert diagnostics[-1]["pass_rate"] == 0.5

    dataframe = dashboard_entry_diagnostics(
        db_path=db_path,
    )

    assert list(dataframe["gate"]) == [
        row[0]
        for row in expected
    ]
    assert list(dataframe["failed"]) == [1] * 8


def test_empty_entry_diagnostics(
    tmp_path: Path,
) -> None:
    diagnostics = paper_entry_diagnostics(
        tmp_path / "empty.db"
    )

    assert len(diagnostics) == 8
    assert all(
        row["total_decisions"] == 0
        and row["evaluated"] == 0
        and row["passed"] == 0
        and row["failed"] == 0
        and row["pass_rate"] == 0.0
        for row in diagnostics
    )
