from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .db import DEFAULT_DB_PATH, database_connection


TRADE_SCHEMA = """
CREATE TABLE IF NOT EXISTS coinbase_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT,
    product_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    side TEXT,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(product_id, trade_id)
);

CREATE INDEX IF NOT EXISTS idx_coinbase_trades_timestamp
ON coinbase_trades(timestamp);

CREATE INDEX IF NOT EXISTS idx_coinbase_trades_product_timestamp
ON coinbase_trades(product_id, timestamp);
"""


def initialize_trade_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Path:
    """Create the Coinbase trade table and indexes."""
    path = Path(db_path)

    with database_connection(path) as connection:
        connection.executescript(TRADE_SCHEMA)

    return path


def save_coinbase_trade(
    trade: dict[str, Any],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """
    Save one normalized Coinbase trade.

    Returns True when a new row was inserted and False when the trade
    was already stored.
    """
    initialize_trade_store(db_path)

    required_fields = ("product_id", "timestamp", "price", "size")
    missing_fields = [
        field for field in required_fields if trade.get(field) is None
    ]

    if missing_fields:
        raise ValueError(
            "Trade is missing required fields: "
            + ", ".join(missing_fields)
        )

    with database_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO coinbase_trades (
                trade_id,
                product_id,
                timestamp,
                price,
                size,
                side
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                trade.get("trade_id"),
                str(trade["product_id"]),
                str(trade["timestamp"]),
                float(trade["price"]),
                float(trade["size"]),
                trade.get("side"),
            ),
        )

        return cursor.rowcount == 1


def trade_count(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """Return the total number of recorded Coinbase trades."""
    initialize_trade_store(db_path)

    with database_connection(db_path) as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM coinbase_trades"
        ).fetchone()

    return int(row["count"])


def latest_trade(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Return the most recently recorded Coinbase trade."""
    initialize_trade_store(db_path)

    with database_connection(db_path) as connection:
        row: sqlite3.Row | None = connection.execute(
            """
            SELECT
                trade_id,
                product_id,
                timestamp,
                price,
                size,
                side
            FROM coinbase_trades
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

    return dict(row) if row is not None else None