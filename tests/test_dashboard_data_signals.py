from __future__ import annotations

from pathlib import Path

import pandas as pd

from kalshi_quant.dashboard_data import recent_signal_history
from kalshi_quant.market_signal import MarketSignal
from kalshi_quant.signal_store import save_market_signal


def signal(timestamp: str, score: float) -> MarketSignal:
    return MarketSignal(
        timestamp=timestamp,
        direction="BULLISH" if score > 0 else "BEARISH",
        action="NO_TRADE",
        score=score,
        probability_up=0.60,
        confidence=0.30,
        volatility_regime="NORMAL",
        trend_score=5.0,
        momentum_score=4.0,
        vwap_score=3.0,
        rsi_score=2.0,
        order_flow_score=1.0,
        order_flow_imbalance=0.10,
        order_flow_reliability=0.80,
        timeframe_confirmation="AGREE",
        timeframe_agreement=1.0,
        reason="Test signal.",
    )


def test_recent_signal_history_is_chronological(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "dashboard-signals.sqlite3"

    save_market_signal(
        signal("2026-07-28T12:00:10+00:00", 10.0),
        db_path=db_path,
    )
    save_market_signal(
        signal("2026-07-28T12:00:15+00:00", 20.0),
        db_path=db_path,
    )

    dataframe = recent_signal_history(
        limit=10,
        db_path=db_path,
    )

    assert list(dataframe["score"]) == [10.0, 20.0]
    assert pd.api.types.is_datetime64_any_dtype(
        dataframe["timestamp"]
    )
