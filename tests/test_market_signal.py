from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from kalshi_quant.market_signal import (
    MarketSignal,
    evaluate_market_signal,
)


def make_bars(
    closes: np.ndarray,
    *,
    imbalance: float | np.ndarray,
    volume: float | np.ndarray = 10.0,
) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate(([closes[0]], closes[:-1]))

    volumes = np.broadcast_to(
        np.asarray(volume, dtype=float),
        closes.shape,
    ).copy()
    imbalances = np.broadcast_to(
        np.asarray(imbalance, dtype=float),
        closes.shape,
    ).copy()

    buy_share = (imbalances + 1.0) / 2.0
    buy_volume = volumes * buy_share
    sell_volume = volumes - buy_volume

    return pd.DataFrame(
        {
            "start_time": pd.date_range(
                "2026-07-28",
                periods=len(closes),
                freq="min",
                tz="UTC",
            ),
            "open": opens,
            "high": np.maximum(opens, closes) + 0.25,
            "low": np.minimum(opens, closes) - 0.25,
            "close": closes,
            "volume": volumes,
            "trade_count": np.full(len(closes), 25),
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "volume_imbalance": imbalances,
        }
    )


def test_bullish_market_produces_long_bias() -> None:
    signal = evaluate_market_signal(
        make_bars(
            np.linspace(100.0, 120.0, 80),
            imbalance=0.65,
        )
    )

    assert isinstance(signal, MarketSignal)
    assert signal.direction == "BULLISH"
    assert signal.action == "LONG_BIAS"
    assert signal.score > 25
    assert signal.probability_up > 0.50
    assert signal.order_flow_imbalance == pytest.approx(0.65)
    assert signal.order_flow_reliability == pytest.approx(1.0)


def test_bearish_market_produces_short_bias() -> None:
    signal = evaluate_market_signal(
        make_bars(
            np.linspace(120.0, 100.0, 80),
            imbalance=-0.65,
        )
    )

    assert signal.direction == "BEARISH"
    assert signal.action == "SHORT_BIAS"
    assert signal.score < -25
    assert signal.probability_up < 0.50


def test_flat_balanced_market_avoids_trade() -> None:
    signal = evaluate_market_signal(
        make_bars(
            np.full(80, 100.0),
            imbalance=0.0,
        )
    )

    assert signal.direction == "NEUTRAL"
    assert signal.action == "NO_TRADE"
    assert abs(signal.score) < 10
    assert signal.probability_up == pytest.approx(
        0.50,
        abs=0.02,
    )


def test_tiny_latest_bar_does_not_dominate_order_flow() -> None:
    imbalances = np.zeros(80)
    volumes = np.full(80, 10.0)

    imbalances[-1] = -1.0
    volumes[-1] = 0.000001

    signal = evaluate_market_signal(
        make_bars(
            np.full(80, 100.0),
            imbalance=imbalances,
            volume=volumes,
        )
    )

    assert abs(signal.order_flow_imbalance) < 0.01
    assert abs(signal.order_flow_score) < 0.25
    assert signal.action == "NO_TRADE"


def test_sparse_recent_volume_reduces_order_flow_reliability() -> None:
    volumes = np.full(80, 10.0)
    volumes[-12:] = 0.1

    signal = evaluate_market_signal(
        make_bars(
            np.full(80, 100.0),
            imbalance=1.0,
            volume=volumes,
        )
    )

    assert signal.order_flow_imbalance == pytest.approx(1.0)
    assert signal.order_flow_reliability < 0.35
    assert signal.order_flow_score < 10.0


def test_confirmation_agreement_increases_confidence() -> None:
    primary = make_bars(
        np.linspace(100.0, 120.0, 80),
        imbalance=0.50,
    )
    agreeing = make_bars(
        np.linspace(100.0, 115.0, 80),
        imbalance=0.40,
    )
    conflicting = make_bars(
        np.linspace(120.0, 100.0, 80),
        imbalance=-0.50,
    )

    agreed_signal = evaluate_market_signal(
        primary,
        confirmation_bars=agreeing,
    )
    conflicted_signal = evaluate_market_signal(
        primary,
        confirmation_bars=conflicting,
    )

    assert agreed_signal.timeframe_confirmation == "AGREE"
    assert conflicted_signal.timeframe_confirmation == "CONFLICT"
    assert agreed_signal.confidence > conflicted_signal.confidence


def test_short_confirmation_history_is_ignored() -> None:
    primary = make_bars(
        np.linspace(100.0, 120.0, 80),
        imbalance=0.50,
    )
    short_confirmation = make_bars(
        np.linspace(100.0, 101.0, 10),
        imbalance=0.10,
    )

    signal = evaluate_market_signal(
        primary,
        confirmation_bars=short_confirmation,
    )

    assert signal.timeframe_confirmation == "UNAVAILABLE"


def test_probability_and_confidence_are_bounded() -> None:
    signal = evaluate_market_signal(
        make_bars(
            np.linspace(100.0, 135.0, 80),
            imbalance=1.0,
        )
    )

    assert 0.05 <= signal.probability_up <= 0.95
    assert 0.0 <= signal.confidence <= 1.0


def test_too_few_bars_raise_error() -> None:
    bars = make_bars(
        np.linspace(100.0, 101.0, 10),
        imbalance=0.1,
    )

    with pytest.raises(ValueError, match="At least 20 bars"):
        evaluate_market_signal(bars)


def test_missing_columns_raise_error() -> None:
    bars = pd.DataFrame(
        {
            "close": np.linspace(100.0, 105.0, 30),
        }
    )

    with pytest.raises(ValueError, match="Missing required columns"):
        evaluate_market_signal(bars)
