from __future__ import annotations

from pathlib import Path

from kalshi_quant.market_signal import MarketSignal
from kalshi_quant.signal_store import (
    latest_market_signal,
    recent_market_signals,
    save_market_signal,
    signal_history_count,
)


def sample_signal(
    *,
    score: float = 31.5,
) -> MarketSignal:
    return MarketSignal(
        timestamp="2026-07-28T13:00:00+00:00",
        direction="BULLISH",
        action="LONG_BIAS",
        score=score,
        probability_up=0.807,
        confidence=0.52,
        volatility_regime="NORMAL",
        trend_score=18.0,
        momentum_score=7.0,
        vwap_score=5.0,
        rsi_score=4.0,
        order_flow_score=-2.5,
        order_flow_imbalance=-0.20,
        order_flow_reliability=0.50,
        timeframe_confirmation="AGREE",
        timeframe_agreement=1.0,
        reason="Test signal.",
    )


def test_save_and_load_signal_history(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "signals.sqlite3"

    save_market_signal(
        sample_signal(),
        product_id="BTC-USD",
        interval_seconds=5,
        db_path=db_path,
    )

    assert signal_history_count(
        product_id="BTC-USD",
        interval_seconds=5,
        db_path=db_path,
    ) == 1

    stored = latest_market_signal(
        product_id="BTC-USD",
        interval_seconds=5,
        db_path=db_path,
    )

    assert stored is not None
    assert stored["direction"] == "BULLISH"
    assert stored["score"] == 31.5
    assert stored["timeframe_confirmation"] == "AGREE"


def test_duplicate_timestamp_updates_existing_signal(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "signals.sqlite3"

    save_market_signal(
        sample_signal(score=31.5),
        interval_seconds=5,
        db_path=db_path,
    )
    save_market_signal(
        sample_signal(score=42.0),
        interval_seconds=5,
        db_path=db_path,
    )

    assert signal_history_count(
        interval_seconds=5,
        db_path=db_path,
    ) == 1

    stored = latest_market_signal(
        interval_seconds=5,
        db_path=db_path,
    )

    assert stored is not None
    assert stored["score"] == 42.0


def test_recent_signal_limit(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "signals.sqlite3"

    for index in range(3):
        signal = sample_signal(score=10.0 + index)
        signal = MarketSignal(
            **{
                **signal.as_dict(),
                "timestamp": (
                    f"2026-07-28T13:00:0{index}+00:00"
                ),
            }
        )
        save_market_signal(
            signal,
            interval_seconds=60,
            db_path=db_path,
        )

    rows = recent_market_signals(
        interval_seconds=60,
        limit=2,
        db_path=db_path,
    )

    assert len(rows) == 2
    assert rows[0]["score"] == 12.0
