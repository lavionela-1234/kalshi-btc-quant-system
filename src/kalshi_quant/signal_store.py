from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .db import DEFAULT_DB_PATH, database_connection, utc_now
from .market_signal import MarketSignal


SIGNAL_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS technical_signal_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL,
    timestamp TEXT NOT NULL,

    direction TEXT NOT NULL,
    action TEXT NOT NULL,
    score REAL NOT NULL,
    probability_up REAL NOT NULL,
    confidence REAL NOT NULL,
    volatility_regime TEXT NOT NULL,

    trend_score REAL NOT NULL,
    momentum_score REAL NOT NULL,
    vwap_score REAL NOT NULL,
    rsi_score REAL NOT NULL,
    order_flow_score REAL NOT NULL,
    order_flow_imbalance REAL NOT NULL,
    order_flow_reliability REAL NOT NULL,

    timeframe_confirmation TEXT NOT NULL,
    timeframe_agreement REAL NOT NULL,
    reason TEXT NOT NULL,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(product_id, interval_seconds, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_technical_signal_history_lookup
ON technical_signal_history(
    product_id,
    interval_seconds,
    timestamp
);
"""


def initialize_signal_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Path:
    """Create the technical-signal history table and index."""
    path = Path(db_path)

    with database_connection(path) as connection:
        connection.executescript(SIGNAL_HISTORY_SCHEMA)

    return path


def save_market_signal(
    signal: MarketSignal,
    *,
    product_id: str = "BTC-USD",
    interval_seconds: int = 5,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    """Insert or update one technical market signal."""
    if interval_seconds <= 0:
        raise ValueError(
            "interval_seconds must be greater than zero"
        )

    initialize_signal_store(db_path)
    timestamp = signal.timestamp or utc_now()

    with database_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO technical_signal_history (
                product_id,
                interval_seconds,
                timestamp,
                direction,
                action,
                score,
                probability_up,
                confidence,
                volatility_regime,
                trend_score,
                momentum_score,
                vwap_score,
                rsi_score,
                order_flow_score,
                order_flow_imbalance,
                order_flow_reliability,
                timeframe_confirmation,
                timeframe_agreement,
                reason
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(
                product_id,
                interval_seconds,
                timestamp
            )
            DO UPDATE SET
                direction = excluded.direction,
                action = excluded.action,
                score = excluded.score,
                probability_up = excluded.probability_up,
                confidence = excluded.confidence,
                volatility_regime = excluded.volatility_regime,
                trend_score = excluded.trend_score,
                momentum_score = excluded.momentum_score,
                vwap_score = excluded.vwap_score,
                rsi_score = excluded.rsi_score,
                order_flow_score = excluded.order_flow_score,
                order_flow_imbalance = excluded.order_flow_imbalance,
                order_flow_reliability = excluded.order_flow_reliability,
                timeframe_confirmation = excluded.timeframe_confirmation,
                timeframe_agreement = excluded.timeframe_agreement,
                reason = excluded.reason,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                product_id,
                interval_seconds,
                timestamp,
                signal.direction,
                signal.action,
                signal.score,
                signal.probability_up,
                signal.confidence,
                signal.volatility_regime,
                signal.trend_score,
                signal.momentum_score,
                signal.vwap_score,
                signal.rsi_score,
                signal.order_flow_score,
                signal.order_flow_imbalance,
                signal.order_flow_reliability,
                signal.timeframe_confirmation,
                signal.timeframe_agreement,
                signal.reason,
            ),
        )


def signal_history_count(
    *,
    product_id: str = "BTC-USD",
    interval_seconds: int | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """Return the number of stored technical signals."""
    initialize_signal_store(db_path)

    with database_connection(db_path) as connection:
        if interval_seconds is None:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM technical_signal_history
                WHERE product_id = ?
                """,
                (product_id,),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM technical_signal_history
                WHERE product_id = ?
                  AND interval_seconds = ?
                """,
                (
                    product_id,
                    interval_seconds,
                ),
            ).fetchone()

    return int(row["count"])


def signal_calibration_report(
    *,
    product_id: str = "BTC-USD",
    interval_seconds: int = 5,
    scenarios: list[tuple[float, float]] | None = None,
    episode_gap_seconds: float = 15.0,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Summarize signal strength and independent candidate episodes."""

    if interval_seconds <= 0:
        raise ValueError(
            "interval_seconds must be greater than zero"
        )

    if episode_gap_seconds <= 0.0:
        raise ValueError(
            "episode_gap_seconds must be greater than zero"
        )

    if scenarios is None:
        scenarios = [
            (15.0, 0.15),
            (18.0, 0.15),
            (20.0, 0.15),
            (20.0, 0.20),
            (22.0, 0.20),
            (25.0, 0.25),
            (30.0, 0.30),
        ]

    normalized_scenarios: list[tuple[float, float]] = []

    for score_threshold, confidence_threshold in scenarios:
        score_value = float(score_threshold)
        confidence_value = float(confidence_threshold)

        if score_value < 0.0:
            raise ValueError(
                "score thresholds must not be negative"
            )

        if not 0.0 <= confidence_value <= 1.0:
            raise ValueError(
                "confidence thresholds must be between zero and one"
            )

        normalized_scenarios.append(
            (score_value, confidence_value)
        )

    initialize_signal_store(db_path)

    with database_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                timestamp,
                direction,
                action,
                score,
                confidence,
                probability_up,
                volatility_regime
            FROM technical_signal_history
            WHERE product_id = ?
              AND interval_seconds = ?
            ORDER BY timestamp, id
            """,
            (
                product_id,
                interval_seconds,
            ),
        ).fetchall()

    total_signals = len(rows)

    action_names = [
        "LONG_BIAS",
        "SHORT_BIAS",
        "NO_TRADE",
    ]
    action_counts = {
        action: 0
        for action in action_names
    }

    for row in rows:
        action = str(row["action"])
        action_counts[action] = (
            action_counts.get(action, 0) + 1
        )

    scores = [
        float(row["score"])
        for row in rows
    ]
    absolute_scores = [
        abs(score)
        for score in scores
    ]
    confidences = [
        float(row["confidence"])
        for row in rows
    ]

    summary = {
        "product_id": product_id,
        "interval_seconds": interval_seconds,
        "episode_gap_seconds": episode_gap_seconds,
        "total_signals": total_signals,
        "first_timestamp": (
            str(rows[0]["timestamp"])
            if rows
            else None
        ),
        "last_timestamp": (
            str(rows[-1]["timestamp"])
            if rows
            else None
        ),
        "long_bias_count": action_counts.get(
            "LONG_BIAS",
            0,
        ),
        "short_bias_count": action_counts.get(
            "SHORT_BIAS",
            0,
        ),
        "no_trade_count": action_counts.get(
            "NO_TRADE",
            0,
        ),
        "minimum_score": (
            min(scores)
            if scores
            else None
        ),
        "maximum_score": (
            max(scores)
            if scores
            else None
        ),
        "average_absolute_score": (
            sum(absolute_scores) / total_signals
            if total_signals
            else 0.0
        ),
        "average_confidence": (
            sum(confidences) / total_signals
            if total_signals
            else 0.0
        ),
        "maximum_confidence": (
            max(confidences)
            if confidences
            else 0.0
        ),
    }

    action_rows = []

    for action in action_names:
        count = action_counts.get(action, 0)

        action_rows.append(
            {
                "action": action,
                "count": count,
                "rate": (
                    count / total_signals
                    if total_signals
                    else 0.0
                ),
            }
        )

    def candidate_episode_summary(
        score_threshold: float,
        confidence_threshold: float,
    ) -> dict[str, float | int]:
        episodes: list[dict[str, Any]] = []
        active_episode: dict[str, Any] | None = None

        for row in rows:
            score = float(row["score"])
            confidence = float(row["confidence"])

            direction = (
                "LONG"
                if score >= score_threshold
                and confidence >= confidence_threshold
                else "SHORT"
                if score <= -score_threshold
                and confidence >= confidence_threshold
                else None
            )

            timestamp = datetime.fromisoformat(
                str(row["timestamp"]).replace(
                    "Z",
                    "+00:00",
                )
            )

            if direction is None:
                if active_episode is not None:
                    episodes.append(active_episode)
                    active_episode = None
                continue

            if active_episode is not None:
                gap = (
                    timestamp
                    - active_episode["last_timestamp"]
                ).total_seconds()

                if (
                    active_episode["direction"] == direction
                    and gap <= episode_gap_seconds
                ):
                    active_episode["signal_count"] += 1
                    active_episode["last_timestamp"] = timestamp
                    continue

                episodes.append(active_episode)

            active_episode = {
                "direction": direction,
                "signal_count": 1,
                "first_timestamp": timestamp,
                "last_timestamp": timestamp,
            }

        if active_episode is not None:
            episodes.append(active_episode)

        episode_count = len(episodes)
        episode_signal_total = sum(
            int(episode["signal_count"])
            for episode in episodes
        )

        return {
            "candidate_episode_count": episode_count,
            "long_episodes": sum(
                episode["direction"] == "LONG"
                for episode in episodes
            ),
            "short_episodes": sum(
                episode["direction"] == "SHORT"
                for episode in episodes
            ),
            "average_signals_per_episode": (
                episode_signal_total / episode_count
                if episode_count
                else 0.0
            ),
        }

    threshold_rows = []

    for score_threshold, confidence_threshold in (
        normalized_scenarios
    ):
        long_candidates = sum(
            score >= score_threshold
            and confidence >= confidence_threshold
            for score, confidence in zip(
                scores,
                confidences,
            )
        )
        short_candidates = sum(
            score <= -score_threshold
            and confidence >= confidence_threshold
            for score, confidence in zip(
                scores,
                confidences,
            )
        )
        candidate_count = (
            long_candidates + short_candidates
        )

        episode_metrics = candidate_episode_summary(
            score_threshold,
            confidence_threshold,
        )

        threshold_rows.append(
            {
                "score_threshold": score_threshold,
                "confidence_threshold": (
                    confidence_threshold
                ),
                "candidate_count": candidate_count,
                "candidate_rate": (
                    candidate_count / total_signals
                    if total_signals
                    else 0.0
                ),
                "long_candidates": long_candidates,
                "short_candidates": short_candidates,
                **episode_metrics,
                "theoretical_candidate_signals_per_hour": (
                    candidate_count / total_signals
                    * (3600.0 / interval_seconds)
                    if total_signals
                    else 0.0
                ),
            }
        )

    score_bucket_definitions = [
        ("0 to <10", 0.0, 10.0),
        ("10 to <15", 10.0, 15.0),
        ("15 to <20", 15.0, 20.0),
        ("20 to <25", 20.0, 25.0),
        ("25 to <30", 25.0, 30.0),
        ("30 or more", 30.0, None),
    ]

    score_buckets = []

    for label, lower, upper in score_bucket_definitions:
        if upper is None:
            count = sum(
                value >= lower
                for value in absolute_scores
            )
        else:
            count = sum(
                lower <= value < upper
                for value in absolute_scores
            )

        score_buckets.append(
            {
                "score_bucket": label,
                "count": count,
                "rate": (
                    count / total_signals
                    if total_signals
                    else 0.0
                ),
            }
        )

    return {
        "summary": summary,
        "action_counts": action_rows,
        "threshold_scenarios": threshold_rows,
        "score_buckets": score_buckets,
    }



def latest_market_signal(
    *,
    product_id: str = "BTC-USD",
    interval_seconds: int = 5,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Return the newest stored technical signal."""
    initialize_signal_store(db_path)

    with database_connection(db_path) as connection:
        row = connection.execute(
            """
            SELECT
                product_id,
                interval_seconds,
                timestamp,
                direction,
                action,
                score,
                probability_up,
                confidence,
                volatility_regime,
                trend_score,
                momentum_score,
                vwap_score,
                rsi_score,
                order_flow_score,
                order_flow_imbalance,
                order_flow_reliability,
                timeframe_confirmation,
                timeframe_agreement,
                reason
            FROM technical_signal_history
            WHERE product_id = ?
              AND interval_seconds = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (
                product_id,
                interval_seconds,
            ),
        ).fetchone()

    return dict(row) if row is not None else None


def recent_market_signals(
    *,
    product_id: str = "BTC-USD",
    interval_seconds: int = 5,
    limit: int = 200,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """Return recent signals in newest-first order."""
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    initialize_signal_store(db_path)

    with database_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                product_id,
                interval_seconds,
                timestamp,
                direction,
                action,
                score,
                probability_up,
                confidence,
                volatility_regime,
                trend_score,
                momentum_score,
                vwap_score,
                rsi_score,
                order_flow_score,
                order_flow_imbalance,
                order_flow_reliability,
                timeframe_confirmation,
                timeframe_agreement,
                reason
            FROM technical_signal_history
            WHERE product_id = ?
              AND interval_seconds = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (
                product_id,
                interval_seconds,
                limit,
            ),
        ).fetchall()

    return [dict(row) for row in rows]
