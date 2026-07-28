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
    imbalance: float,
) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate(([closes[0]], closes[:-1]))
    volume = np.full(len(closes), 10.0)
    buy_share = (imbalance + 1.0) / 2.0
    buy_volume = volume * buy_share
    sell_volume = volume - buy_volume

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
            "volume": volume,
            "trade_count": np.full(len(closes), 25),
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "volume_imbalance": np.full(len(closes), imbalance),
        }
    )


def test_bullish_market_produces_long_bias() -> None:
    signal = evaluate_market_signal(
        make_bars(np.linspace(100.0, 120.0, 80), imbalance=0.65)
    )
    assert isinstance(signal, MarketSignal)
    assert signal.direction == "BULLISH"
    assert signal.action == "LONG_BIAS"
    assert signal.score > 25
    assert signal.probability_up > 0.50


def test_bearish_market_produces_short_bias() -> None:
    signal = evaluate_market_signal(
        make_bars(np.linspace(120.0, 100.0, 80), imbalance=-0.65)
    )
    assert signal.direction == "BEARISH"
    assert signal.action == "SHORT_BIAS"
    assert signal.score < -25
    assert signal.probability_up < 0.50


def test_flat_balanced_market_avoids_trade() -> None:
    signal = evaluate_market_signal(
        make_bars(np.full(80, 100.0), imbalance=0.0)
    )
    assert signal.direction == "NEUTRAL"
    assert signal.action == "NO_TRADE"
    assert abs(signal.score) < 10
    assert signal.probability_up == pytest.approx(0.50, abs=0.02)


def test_probability_and_confidence_are_bounded() -> None:
    signal = evaluate_market_signal(
        make_bars(np.linspace(100.0, 135.0, 80), imbalance=1.0)
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
        {"close": np.linspace(100.0, 105.0, 30)}
    )
    with pytest.raises(ValueError, match="Missing required columns"):
        evaluate_market_signal(bars)
