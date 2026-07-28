import pandas as pd
import pytest

from kalshi_quant.indicators import (
    add_market_indicators,
    calculate_ema,
    calculate_rsi,
    calculate_vwap,
)


def sample_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104],
            "high": [102, 103, 104, 105, 106],
            "low": [99, 100, 101, 102, 103],
            "close": [101, 102, 103, 104, 105],
            "volume": [10, 12, 11, 15, 14],
            "trade_count": [20, 22, 21, 25, 24],
            "buy_volume": [6, 7, 8, 9, 10],
            "sell_volume": [4, 5, 3, 6, 4],
            "volume_imbalance": [
                0.2,
                0.1667,
                0.4545,
                0.2,
                0.4286,
            ],
        }
    )


def test_calculate_ema_returns_series():
    prices = pd.Series([100, 101, 102, 103])

    ema = calculate_ema(
        prices,
        period=3,
    )

    assert len(ema) == 4
    assert ema.iloc[0] == pytest.approx(100)


def test_calculate_vwap_returns_values():
    bars = sample_bars()

    vwap = calculate_vwap(bars)

    assert len(vwap) == len(bars)
    assert vwap.notna().all()


def test_rsi_is_between_zero_and_one_hundred():
    prices = pd.Series(
        [100, 101, 102, 101, 103, 104, 102, 105]
    )

    rsi = calculate_rsi(
        prices,
        period=3,
    )

    assert rsi.between(0, 100).all()


def test_add_market_indicators_adds_expected_columns():
    result = add_market_indicators(
        sample_bars()
    )

    expected_columns = {
        "return",
        "ema_9",
        "ema_20",
        "ema_50",
        "vwap",
        "rsi_14",
        "volatility_20",
        "buy_pressure",
        "sell_pressure",
    }

    assert expected_columns.issubset(
        result.columns
    )


def test_invalid_ema_period_raises_error():
    with pytest.raises(ValueError):
        calculate_ema(
            pd.Series([100, 101]),
            period=0,
        )