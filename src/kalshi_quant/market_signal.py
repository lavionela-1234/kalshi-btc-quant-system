from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

import numpy as np
import pandas as pd

from .indicators import add_market_indicators


@dataclass(frozen=True)
class MarketSignal:
    timestamp: str | None
    direction: str
    action: str
    score: float
    probability_up: float
    confidence: float
    volatility_regime: str
    trend_score: float
    momentum_score: float
    vwap_score: float
    rsi_score: float
    order_flow_score: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clip(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _scaled_tanh(value: float, scale: float, maximum: float) -> float:
    return maximum * math.tanh(value / scale)


def _volatility_regime(series: pd.Series, latest: float) -> str:
    valid = (
        pd.to_numeric(series, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    valid = valid[valid > 0]

    if valid.empty or latest <= 0:
        return "UNKNOWN"

    baseline = float(valid.median())
    if baseline <= 0:
        return "UNKNOWN"

    ratio = latest / baseline
    if ratio < 0.70:
        return "LOW"
    if ratio > 1.50:
        return "HIGH"
    return "NORMAL"


def _timestamp(dataframe: pd.DataFrame) -> str | None:
    for column in ("end_time", "start_time", "timestamp"):
        if column in dataframe.columns:
            value = dataframe.iloc[-1][column]
            if pd.isna(value):
                return None
            if isinstance(value, pd.Timestamp):
                return value.isoformat()
            return str(value)
    return None


def evaluate_market_signal(
    bars: pd.DataFrame,
    *,
    min_bars: int = 20,
    long_threshold: float = 25.0,
    short_threshold: float = -25.0,
) -> MarketSignal:
    """Create a -100 to +100 technical BTC direction score."""
    if min_bars < 2:
        raise ValueError("min_bars must be at least 2")
    if short_threshold >= long_threshold:
        raise ValueError(
            "short_threshold must be less than long_threshold"
        )
    if bars.empty:
        raise ValueError("bars cannot be empty")
    if len(bars) < min_bars:
        raise ValueError(
            f"At least {min_bars} bars are required; received {len(bars)}"
        )

    required = {
        "open", "high", "low", "close", "volume", "trade_count",
        "buy_volume", "sell_volume", "volume_imbalance",
    }
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(
            "Missing required columns: " + ", ".join(sorted(missing))
        )

    enriched = add_market_indicators(bars)
    latest = enriched.iloc[-1]

    close = _safe_float(latest["close"])
    if close <= 0:
        raise ValueError("Latest close must be greater than zero")

    ema_9 = _safe_float(latest["ema_9"], close)
    ema_20 = _safe_float(latest["ema_20"], close)
    ema_50 = _safe_float(latest["ema_50"], close)
    vwap = _safe_float(latest["vwap"], close)
    rsi = _safe_float(latest["rsi_14"], 50.0)
    imbalance = _clip(
        _safe_float(latest["volume_imbalance"]),
        -1.0,
        1.0,
    )
    volatility = max(
        _safe_float(latest["volatility_20"]),
        0.0,
    )
    scale = max(volatility, 0.00010)

    trend_score = _clip(
        _scaled_tanh((ema_9 - ema_20) / close, scale, 15.0)
        + _scaled_tanh(
            (ema_20 - ema_50) / close,
            scale * 1.5,
            10.0,
        ),
        -25.0,
        25.0,
    )

    closes = pd.to_numeric(
        enriched["close"],
        errors="coerce",
    ).astype(float)
    ret_1 = close / float(closes.iloc[-2]) - 1.0
    ret_3 = close / float(closes.iloc[-4]) - 1.0
    ret_5 = close / float(closes.iloc[-6]) - 1.0
    momentum = 0.50 * ret_1 + 0.30 * ret_3 + 0.20 * ret_5

    momentum_score = _clip(
        _scaled_tanh(momentum, scale * 1.5, 20.0),
        -20.0,
        20.0,
    )
    vwap_score = _clip(
        _scaled_tanh(
            (close - vwap) / close,
            scale * 2.0,
            15.0,
        ),
        -15.0,
        15.0,
    )
    rsi_score = _clip((rsi - 50.0) / 20.0, -1.0, 1.0) * 15.0
    order_flow_score = imbalance * 25.0

    score = _clip(
        trend_score
        + momentum_score
        + vwap_score
        + rsi_score
        + order_flow_score,
        -100.0,
        100.0,
    )

    probability_up = _clip(
        1.0 / (1.0 + math.exp(-score / 22.0)),
        0.05,
        0.95,
    )

    regime = _volatility_regime(
        enriched["volatility_20"],
        volatility,
    )
    data_quality = min(len(enriched) / (min_bars * 2), 1.0)
    regime_factor = {
        "LOW": 0.85,
        "NORMAL": 1.00,
        "HIGH": 0.80,
        "UNKNOWN": 0.70,
    }[regime]
    confidence = _clip(
        abs(score) / 60.0 * data_quality * regime_factor,
        0.0,
        1.0,
    )

    action = (
        "LONG_BIAS"
        if score >= long_threshold
        else "SHORT_BIAS"
        if score <= short_threshold
        else "NO_TRADE"
    )
    direction = (
        "BULLISH"
        if score >= 10.0
        else "BEARISH"
        if score <= -10.0
        else "NEUTRAL"
    )

    components = {
        "trend": trend_score,
        "momentum": momentum_score,
        "vwap": vwap_score,
        "rsi": rsi_score,
        "order flow": order_flow_score,
    }
    strongest = sorted(
        components.items(),
        key=lambda item: abs(item[1]),
        reverse=True,
    )[:3]
    strongest_text = ", ".join(
        f"{name} {value:+.1f}"
        for name, value in strongest
    )

    return MarketSignal(
        timestamp=_timestamp(enriched),
        direction=direction,
        action=action,
        score=round(score, 4),
        probability_up=round(probability_up, 6),
        confidence=round(confidence, 6),
        volatility_regime=regime,
        trend_score=round(trend_score, 4),
        momentum_score=round(momentum_score, 4),
        vwap_score=round(vwap_score, 4),
        rsi_score=round(rsi_score, 4),
        order_flow_score=round(order_flow_score, 4),
        reason=(
            f"{direction} technical score {score:+.1f}; "
            f"strongest components: {strongest_text}; "
            f"volatility regime: {regime.lower()}."
        ),
    )
