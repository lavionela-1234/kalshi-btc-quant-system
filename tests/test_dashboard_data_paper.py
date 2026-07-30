from __future__ import annotations

from pathlib import Path

from kalshi_quant.dashboard_data import (
    paper_trading_summary,
    recent_paper_decisions,
    recent_paper_trades,
)


def test_empty_paper_dashboard_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "dashboard-paper.db"

    summary = paper_trading_summary(db_path)
    decisions = recent_paper_decisions(db_path=db_path)
    trades = recent_paper_trades(db_path=db_path)

    assert summary["total_trades"] == 0
    assert summary["total_decisions"] == 0
    assert decisions.empty
    assert trades.empty
