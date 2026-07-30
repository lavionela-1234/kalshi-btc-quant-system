from __future__ import annotations

from pathlib import Path

from kalshi_quant.dashboard_data import (
    paper_bankroll_history,
    paper_trading_summary,
    recent_paper_trades,
)


def test_empty_settlement_dashboard_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "dashboard-settlement.db"

    summary = paper_trading_summary(
        db_path,
        starting_bankroll=2500.0,
    )
    history = paper_bankroll_history(
        db_path=db_path,
    )
    trades = recent_paper_trades(
        db_path=db_path,
    )

    assert summary["starting_bankroll"] == 2500.0
    assert summary["current_bankroll"] == 2500.0
    assert summary["closed_trades"] == 0
    assert summary["win_rate"] == 0.0
    assert summary["max_drawdown"] == 0.0
    assert history.empty
    assert trades.empty
