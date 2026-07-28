from __future__ import annotations

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
