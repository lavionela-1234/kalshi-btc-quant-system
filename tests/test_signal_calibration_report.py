from __future__ import annotations

from pathlib import Path

import pandas as pd

from kalshi_quant.dashboard_data import (
    signal_calibration_report as dashboard_calibration_report,
)
from kalshi_quant.market_signal import MarketSignal
from kalshi_quant.signal_store import (
    save_market_signal,
    signal_calibration_report,
)


def make_signal(
    second: int,
    *,
    score: float,
    confidence: float,
    action: str,
) -> MarketSignal:
    direction = (
        "BULLISH"
        if score >= 10.0
        else "BEARISH"
        if score <= -10.0
        else "NEUTRAL"
    )

    return MarketSignal(
        timestamp=(
            f"2026-07-31T12:00:{second:02d}+00:00"
        ),
        direction=direction,
        action=action,
        score=score,
        probability_up=0.50,
        confidence=confidence,
        volatility_regime="NORMAL",
        trend_score=0.0,
        momentum_score=0.0,
        vwap_score=0.0,
        rsi_score=0.0,
        order_flow_score=0.0,
        order_flow_imbalance=0.0,
        order_flow_reliability=1.0,
        timeframe_confirmation="PARTIAL",
        timeframe_agreement=0.80,
        reason="Calibration test signal",
    )


def test_signal_calibration_report(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "calibration.db"

    signals = [
        make_signal(
            5,
            score=-35.0,
            confidence=0.40,
            action="SHORT_BIAS",
        ),
        make_signal(
            10,
            score=-18.0,
            confidence=0.20,
            action="NO_TRADE",
        ),
        make_signal(
            15,
            score=0.0,
            confidence=0.05,
            action="NO_TRADE",
        ),
        make_signal(
            20,
            score=16.0,
            confidence=0.16,
            action="NO_TRADE",
        ),
        make_signal(
            25,
            score=26.0,
            confidence=0.26,
            action="LONG_BIAS",
        ),
        make_signal(
            30,
            score=45.0,
            confidence=0.70,
            action="LONG_BIAS",
        ),
    ]

    for signal in signals:
        save_market_signal(
            signal,
            db_path=db_path,
        )

    report = signal_calibration_report(
        db_path=db_path,
    )

    summary = report["summary"]

    assert summary["total_signals"] == 6
    assert summary["long_bias_count"] == 2
    assert summary["short_bias_count"] == 1
    assert summary["no_trade_count"] == 3
    assert summary["minimum_score"] == -35.0
    assert summary["maximum_score"] == 45.0
    assert summary["episode_gap_seconds"] == 15.0

    current_scenario = next(
        row
        for row in report["threshold_scenarios"]
        if row["score_threshold"] == 25.0
        and row["confidence_threshold"] == 0.25
    )

    assert current_scenario["candidate_count"] == 3
    assert current_scenario["long_candidates"] == 2
    assert current_scenario["short_candidates"] == 1
    assert current_scenario["candidate_rate"] == 0.5
    assert current_scenario["candidate_episode_count"] == 2
    assert current_scenario["long_episodes"] == 1
    assert current_scenario["short_episodes"] == 1
    assert (
        current_scenario["average_signals_per_episode"]
        == 1.5
    )

    buckets = {
        row["score_bucket"]: row["count"]
        for row in report["score_buckets"]
    }

    assert buckets == {
        "0 to <10": 1,
        "10 to <15": 0,
        "15 to <20": 2,
        "20 to <25": 0,
        "25 to <30": 1,
        "30 or more": 2,
    }

    dashboard_report = dashboard_calibration_report(
        db_path=db_path,
    )

    assert isinstance(
        dashboard_report["action_counts"],
        pd.DataFrame,
    )
    assert isinstance(
        dashboard_report["threshold_scenarios"],
        pd.DataFrame,
    )
    assert isinstance(
        dashboard_report["score_buckets"],
        pd.DataFrame,
    )


def test_empty_signal_calibration_report(
    tmp_path: Path,
) -> None:
    report = signal_calibration_report(
        db_path=tmp_path / "empty.db",
    )

    assert report["summary"]["total_signals"] == 0
    assert report["summary"]["minimum_score"] is None
    assert report["summary"]["maximum_score"] is None

    assert all(
        row["candidate_count"] == 0
        and row["candidate_rate"] == 0.0
        and row["candidate_episode_count"] == 0
        and row["average_signals_per_episode"] == 0.0
        for row in report["threshold_scenarios"]
    )
