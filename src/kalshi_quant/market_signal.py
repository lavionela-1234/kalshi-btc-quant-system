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
    order_flow_imbalance: float
    order_flow_reliability: float
    timeframe_confirmation: str
    timeframe_agreement: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _TimeframeAssessment:
    timestamp: str | None
    score: float
    volatility_regime: str
    trend_score: float
    momentum_score: float
    vwap_score: float
    rsi_score: float
    order_flow_score: float
    order_flow_imbalance: float
    order_flow_reliability: float
    component_agreement: float
    data_quality: float


def _clip(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _scaled_tanh(value: float, scale: float, maximum: float) -> float:
    if scale <= 0:
        raise ValueError("scale must be greater than zero")
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
        if column not in dataframe.columns:
            continue
        value = dataframe.iloc[-1][column]
        if pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        return str(value)
    return None


def _weighted_order_flow(
    dataframe: pd.DataFrame,
    *,
    window: int,
    baseline_window: int,
    minimum_volume_ratio: float,
    minimum_directional_volume: float,
) -> tuple[float, float]:
    """
    Return multi-bar imbalance and a 0-1 reliability weight.

    Imbalance is based on summed buy and sell volume, not the latest bar.
    Reliability falls when recent directional volume is sparse relative to
    the market's own recent baseline.
    """
    if window <= 0:
        raise ValueError("order_flow_window must be greater than zero")
    if baseline_window < window:
        raise ValueError(
            "volume_baseline_window must be at least order_flow_window"
        )
    if not 0 < minimum_volume_ratio <= 1:
        raise ValueError(
            "minimum_volume_ratio must be between zero and one"
        )
    if minimum_directional_volume < 0:
        raise ValueError(
            "minimum_directional_volume cannot be negative"
        )

    buy = pd.to_numeric(
        dataframe["buy_volume"],
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0)
    sell = pd.to_numeric(
        dataframe["sell_volume"],
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0)
    directional = buy + sell

    recent_buy = buy.tail(window)
    recent_sell = sell.tail(window)
    recent_directional = directional.tail(window)

    total_directional = float(recent_directional.sum())
    if total_directional <= minimum_directional_volume:
        return 0.0, 0.0

    imbalance = _clip(
        (
            float(recent_buy.sum())
            - float(recent_sell.sum())
        )
        / total_directional,
        -1.0,
        1.0,
    )

    baseline = directional.tail(baseline_window)
    positive_baseline = baseline[baseline > 0]
    if positive_baseline.empty:
        return imbalance, 0.0

    baseline_median = float(positive_baseline.median())
    recent_average = float(recent_directional.mean())

    if baseline_median <= 0:
        return imbalance, 0.0

    volume_ratio = recent_average / baseline_median
    volume_factor = _clip(
        volume_ratio / minimum_volume_ratio,
        0.0,
        1.0,
    )
    coverage_factor = _clip(
        float((recent_directional > 0).mean()),
        0.0,
        1.0,
    )

    reliability = _clip(
        volume_factor * coverage_factor,
        0.0,
        1.0,
    )
    return imbalance, reliability


def _component_agreement(
    score: float,
    components: list[float],
) -> float:
    total_weight = sum(abs(value) for value in components)
    if total_weight == 0 or abs(score) < 1e-12:
        return 0.5

    score_sign = 1.0 if score > 0 else -1.0
    aligned_weight = sum(
        abs(value)
        for value in components
        if value * score_sign > 0
    )
    return _clip(aligned_weight / total_weight, 0.0, 1.0)


def _assess_timeframe(
    bars: pd.DataFrame,
    *,
    min_bars: int,
    order_flow_window: int,
    volume_baseline_window: int,
    minimum_volume_ratio: float,
    minimum_directional_volume: float,
) -> _TimeframeAssessment:
    if bars.empty:
        raise ValueError("bars cannot be empty")
    if len(bars) < min_bars:
        raise ValueError(
            f"At least {min_bars} bars are required; received {len(bars)}"
        )

    required = {
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
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(sorted(missing))
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
    volatility = max(
        _safe_float(latest["volatility_20"]),
        0.0,
    )
    scale = max(volatility, 0.00010)

    trend_score = _clip(
        _scaled_tanh(
            (ema_9 - ema_20) / close,
            scale,
            15.0,
        )
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
    momentum = (
        0.50 * ret_1
        + 0.30 * ret_3
        + 0.20 * ret_5
    )
    momentum_score = _clip(
        _scaled_tanh(
            momentum,
            scale * 1.5,
            20.0,
        ),
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

    rsi_score = (
        _clip((rsi - 50.0) / 20.0, -1.0, 1.0)
        * 15.0
    )

    order_flow_imbalance, order_flow_reliability = (
        _weighted_order_flow(
            enriched,
            window=order_flow_window,
            baseline_window=volume_baseline_window,
            minimum_volume_ratio=minimum_volume_ratio,
            minimum_directional_volume=minimum_directional_volume,
        )
    )
    order_flow_score = (
        order_flow_imbalance
        * 25.0
        * order_flow_reliability
    )

    components = [
        trend_score,
        momentum_score,
        vwap_score,
        rsi_score,
        order_flow_score,
    ]
    score = _clip(sum(components), -100.0, 100.0)

    return _TimeframeAssessment(
        timestamp=_timestamp(enriched),
        score=score,
        volatility_regime=_volatility_regime(
            enriched["volatility_20"],
            volatility,
        ),
        trend_score=trend_score,
        momentum_score=momentum_score,
        vwap_score=vwap_score,
        rsi_score=rsi_score,
        order_flow_score=order_flow_score,
        order_flow_imbalance=order_flow_imbalance,
        order_flow_reliability=order_flow_reliability,
        component_agreement=_component_agreement(
            score,
            components,
        ),
        data_quality=min(
            len(enriched) / max(min_bars * 2, 1),
            1.0,
        ),
    )


def _timeframe_relationship(
    primary_score: float,
    confirmation_score: float | None,
) -> tuple[str, float]:
    if confirmation_score is None:
        return "UNAVAILABLE", 0.85

    primary_directional = abs(primary_score) >= 10.0
    confirmation_directional = abs(confirmation_score) >= 10.0

    if not primary_directional and not confirmation_directional:
        return "NEUTRAL", 0.90

    if primary_directional and confirmation_directional:
        same_direction = (
            primary_score * confirmation_score > 0
        )
        if same_direction:
            return "AGREE", 1.00
        return "CONFLICT", 0.55

    return "PARTIAL", 0.80


def evaluate_market_signal(
    bars: pd.DataFrame,
    *,
    confirmation_bars: pd.DataFrame | None = None,
    min_bars: int = 20,
    long_threshold: float = 25.0,
    short_threshold: float = -25.0,
    order_flow_window: int = 12,
    volume_baseline_window: int = 60,
    minimum_volume_ratio: float = 0.35,
    minimum_directional_volume: float = 1e-8,
    confirmation_weight: float = 0.25,
) -> MarketSignal:
    """
    Create a robust -100 to +100 technical BTC direction score.

    The primary timeframe drives the signal. An optional confirmation
    timeframe can strengthen or weaken the final score and confidence.
    """
    if min_bars < 6:
        raise ValueError("min_bars must be at least 6")
    if short_threshold >= long_threshold:
        raise ValueError(
            "short_threshold must be less than long_threshold"
        )
    if not 0 <= confirmation_weight <= 0.50:
        raise ValueError(
            "confirmation_weight must be between 0 and 0.50"
        )

    primary = _assess_timeframe(
        bars,
        min_bars=min_bars,
        order_flow_window=order_flow_window,
        volume_baseline_window=volume_baseline_window,
        minimum_volume_ratio=minimum_volume_ratio,
        minimum_directional_volume=minimum_directional_volume,
    )

    confirmation: _TimeframeAssessment | None = None
    if (
        confirmation_bars is not None
        and not confirmation_bars.empty
        and len(confirmation_bars) >= min_bars
    ):
        confirmation = _assess_timeframe(
            confirmation_bars,
            min_bars=min_bars,
            order_flow_window=order_flow_window,
            volume_baseline_window=volume_baseline_window,
            minimum_volume_ratio=minimum_volume_ratio,
            minimum_directional_volume=minimum_directional_volume,
        )

    confirmation_score = (
        confirmation.score
        if confirmation is not None
        else None
    )
    timeframe_confirmation, timeframe_factor = (
        _timeframe_relationship(
            primary.score,
            confirmation_score,
        )
    )

    if confirmation is None:
        score = primary.score
    else:
        score = (
            (1.0 - confirmation_weight) * primary.score
            + confirmation_weight * confirmation.score
        )
    score = _clip(score, -100.0, 100.0)

    probability_up = _clip(
        1.0 / (1.0 + math.exp(-score / 22.0)),
        0.05,
        0.95,
    )

    regime_factor = {
        "LOW": 0.85,
        "NORMAL": 1.00,
        "HIGH": 0.80,
        "UNKNOWN": 0.70,
    }[primary.volatility_regime]

    strength = min(abs(score) / 60.0, 1.0)
    agreement_factor = (
        0.50 + 0.50 * primary.component_agreement
    )
    volume_factor = (
        0.50 + 0.50 * primary.order_flow_reliability
    )

    confidence = _clip(
        strength
        * agreement_factor
        * primary.data_quality
        * regime_factor
        * volume_factor
        * timeframe_factor,
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
        "trend": primary.trend_score,
        "momentum": primary.momentum_score,
        "vwap": primary.vwap_score,
        "rsi": primary.rsi_score,
        "order flow": primary.order_flow_score,
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

    reason = (
        f"{direction} technical score {score:+.1f}; "
        f"strongest components: {strongest_text}; "
        f"multi-bar order flow "
        f"{primary.order_flow_imbalance:+.1%} "
        f"with {primary.order_flow_reliability:.0%} reliability; "
        f"timeframe confirmation: "
        f"{timeframe_confirmation.lower()}; "
        f"volatility regime: "
        f"{primary.volatility_regime.lower()}."
    )

    return MarketSignal(
        timestamp=primary.timestamp,
        direction=direction,
        action=action,
        score=round(score, 4),
        probability_up=round(probability_up, 6),
        confidence=round(confidence, 6),
        volatility_regime=primary.volatility_regime,
        trend_score=round(primary.trend_score, 4),
        momentum_score=round(
            primary.momentum_score,
            4,
        ),
        vwap_score=round(primary.vwap_score, 4),
        rsi_score=round(primary.rsi_score, 4),
        order_flow_score=round(
            primary.order_flow_score,
            4,
        ),
        order_flow_imbalance=round(
            primary.order_flow_imbalance,
            6,
        ),
        order_flow_reliability=round(
            primary.order_flow_reliability,
            6,
        ),
        timeframe_confirmation=timeframe_confirmation,
        timeframe_agreement=round(
            timeframe_factor,
            4,
        ),
        reason=reason,
    )
