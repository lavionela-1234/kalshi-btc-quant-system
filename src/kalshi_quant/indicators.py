from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_ema(
    prices: pd.Series,
    period: int,
) -> pd.Series:
    """Calculate an exponential moving average."""
    if period <= 0:
        raise ValueError("period must be greater than zero")

    return prices.astype(float).ewm(
        span=period,
        adjust=False,
    ).mean()


def calculate_vwap(
    dataframe: pd.DataFrame,
) -> pd.Series:
    """Calculate cumulative VWAP from OHLCV bars."""
    required_columns = {
        "high",
        "low",
        "close",
        "volume",
    }

    missing_columns = required_columns.difference(
        dataframe.columns
    )

    if missing_columns:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(sorted(missing_columns))
        )

    typical_price = (
        dataframe["high"].astype(float)
        + dataframe["low"].astype(float)
        + dataframe["close"].astype(float)
    ) / 3.0

    volume = dataframe["volume"].astype(float)

    cumulative_volume = volume.cumsum()
    cumulative_value = (
        typical_price * volume
    ).cumsum()

    return cumulative_value.div(
        cumulative_volume.replace(0, np.nan)
    )


def calculate_rsi(
    prices: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Calculate the Relative Strength Index."""
    if period <= 0:
        raise ValueError("period must be greater than zero")

    prices = prices.astype(float)
    changes = prices.diff()

    gains = changes.clip(lower=0.0)
    losses = -changes.clip(upper=0.0)

    average_gain = gains.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    average_loss = losses.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    relative_strength = average_gain.div(
        average_loss.replace(0, np.nan)
    )

    rsi = 100 - (
        100 / (1 + relative_strength)
    )

    return rsi.fillna(50.0)


def calculate_rolling_volatility(
    prices: pd.Series,
    window: int = 20,
) -> pd.Series:
    """
    Calculate rolling standard deviation of percentage returns.

    The result is expressed as a decimal return.
    """
    if window <= 1:
        raise ValueError("window must be greater than one")

    returns = prices.astype(float).pct_change()

    return returns.rolling(
        window=window,
        min_periods=2,
    ).std()


def add_market_indicators(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Add professional dashboard indicators to market bars."""
    if dataframe.empty:
        return dataframe.copy()

    required_columns = {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trade_count",
        "buy_volume",
        "sell_volume",
        "volume_imbalance",
    }

    missing_columns = required_columns.difference(
        dataframe.columns
    )

    if missing_columns:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(sorted(missing_columns))
        )

    result = dataframe.copy()

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trade_count",
        "buy_volume",
        "sell_volume",
        "volume_imbalance",
    ]

    for column in numeric_columns:
        result[column] = pd.to_numeric(
            result[column],
            errors="coerce",
        )

    result["return"] = (
        result["close"].pct_change()
    )

    result["ema_9"] = calculate_ema(
        result["close"],
        period=9,
    )

    result["ema_20"] = calculate_ema(
        result["close"],
        period=20,
    )

    result["ema_50"] = calculate_ema(
        result["close"],
        period=50,
    )

    result["vwap"] = calculate_vwap(result)

    result["rsi_14"] = calculate_rsi(
        result["close"],
        period=14,
    )

    result["volatility_20"] = (
        calculate_rolling_volatility(
            result["close"],
            window=20,
        )
    )

    result["buy_pressure"] = (
        result["buy_volume"]
        .div(result["volume"].replace(0, np.nan))
        .fillna(0.0)
    )

    result["sell_pressure"] = (
        result["sell_volume"]
        .div(result["volume"].replace(0, np.nan))
        .fillna(0.0)
    )

    return result