from __future__ import annotations

import sqlite3

import pytest

from kalshi_quant.db import (
    CURRENT_SCHEMA_VERSION,
    connect,
    database_connection,
    initialize_database,
)


def test_database_records_schema_version(tmp_path) -> None:
    db_path = tmp_path / "quant.sqlite3"
    initialize_database(db_path)

    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT MAX(version) AS version FROM schema_versions"
        ).fetchone()
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert row["version"] == CURRENT_SCHEMA_VERSION
    assert journal_mode.lower() == "wal"
    assert busy_timeout == 5000


def test_database_connection_rolls_back_failed_transaction(tmp_path) -> None:
    db_path = tmp_path / "quant.sqlite3"
    initialize_database(db_path)

    with pytest.raises(RuntimeError):
        with database_connection(db_path) as connection:
            connection.execute(
                """
                INSERT INTO system_events (
                    timestamp, level, component, message
                ) VALUES (?, ?, ?, ?)
                """,
                ("2026-08-11T00:00:00+00:00", "INFO", "test", "rollback"),
            )
            raise RuntimeError("interrupt transaction")

    with connect(db_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM system_events"
        ).fetchone()[0]

    assert count == 0


def test_foreign_keys_are_enforced(tmp_path) -> None:
    db_path = tmp_path / "quant.sqlite3"
    initialize_database(db_path)

    with pytest.raises(sqlite3.IntegrityError):
        with database_connection(db_path) as connection:
            connection.execute(
                """
                INSERT INTO snapshots (
                    timestamp, market_ticker
                ) VALUES (?, ?)
                """,
                ("2026-08-11T00:00:00+00:00", "MISSING"),
            )
