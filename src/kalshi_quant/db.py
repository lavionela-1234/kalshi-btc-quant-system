from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


DEFAULT_DB_PATH = Path("data/kalshi_quant.sqlite3")
CURRENT_SCHEMA_VERSION = 1


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_versions (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_versions (version)
VALUES (1);

CREATE TABLE IF NOT EXISTS markets (
    ticker TEXT PRIMARY KEY,
    title TEXT,
    target_price REAL,
    open_time TEXT,
    close_time TEXT,
    status TEXT,
    settlement_value REAL,
    settled_up INTEGER,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    market_ticker TEXT NOT NULL,
    btc_price REAL,
    target_price REAL,
    seconds_remaining REAL,
    yes_bid REAL,
    yes_ask REAL,
    no_bid REAL,
    no_ask REAL,
    model_probability REAL,
    signal TEXT,
    side TEXT,
    edge REAL,
    raw_json TEXT,
    FOREIGN KEY (market_ticker) REFERENCES markets(ticker)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_market_time
ON snapshots(market_ticker, timestamp);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_ticker TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('YES', 'NO')),
    entry_price REAL NOT NULL,
    model_probability REAL,
    edge REAL,
    contracts INTEGER NOT NULL,
    stake REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    closed_at TEXT,
    won INTEGER,
    pnl REAL,
    notes TEXT,
    FOREIGN KEY (market_ticker) REFERENCES markets(ticker)
);

CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    component TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT
);
"""


def utc_now() -> str:
    """Return the current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def connect(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> sqlite3.Connection:
    """Open a connection to the SQLite database."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")

    return connection


@contextmanager
def database_connection(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Iterator[sqlite3.Connection]:
    """Provide a database connection with commit and rollback handling."""
    connection = connect(db_path)

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Path:
    """Create the database and all required tables."""
    path = Path(db_path)

    with database_connection(path) as connection:
        connection.executescript(SCHEMA)

    return path


def database_summary(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Return the number of records in each database table."""
    path = initialize_database(db_path)

    table_names = (
        "markets",
        "snapshots",
        "paper_trades",
        "system_events",
    )

    counts: dict[str, int] = {}

    with database_connection(path) as connection:
        for table_name in table_names:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM {table_name}"
            ).fetchone()

            counts[table_name] = int(row["count"])

    return {
        "database": str(path),
        "tables": counts,
    }


def log_event(
    level: str,
    component: str,
    message: str,
    details: dict[str, Any] | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    """Save a system event to the database."""
    initialize_database(db_path)

    details_json = json.dumps(details) if details is not None else None

    with database_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO system_events (
                timestamp,
                level,
                component,
                message,
                details_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                utc_now(),
                level.upper(),
                component,
                message,
                details_json,
            ),
        )
        