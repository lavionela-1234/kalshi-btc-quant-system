from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .bars import initialize_bar_store
from .db import DEFAULT_DB_PATH, database_connection
from .trade_store import initialize_trade_store


def market_summary(
    product_id: str = "BTC-USD",
    interval_seconds: int = 60,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Return headline Coinbase market statistics."""
    initialize_trade_store(db_path)
    initialize_bar_store(db_path)

    with database_connection(db_path) as connection:
        trade_row = connection.execute(
            """
            SELECT
                COUNT(*) AS trade_count,
                MAX(timestamp) AS latest_trade_time
            FROM coinbase_trades
            WHERE product_id = ?
            """,
            (product_id,),
        ).fetchone()

        latest_trade_row = connection.execute(
            """
            SELECT
                trade_id,
                product_id,
                timestamp,
                price,
                size,
                side
            FROM coinbase_trades
            WHERE product_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (product_id,),
        ).fetchone()

        bar_count_row = connection.execute(
            """
            SELECT COUNT(*) AS bar_count
            FROM coinbase_bars
            WHERE product_id = ?
              AND interval_seconds = ?
            """,
            (product_id, interval_seconds),
        ).fetchone()

        latest_bar_row = connection.execute(
            """
            SELECT
                product_id,
                interval_seconds,
                start_time,
                end_time,
                open,
                high,
                low,
                close,
                volume,
                trade_count,
                buy_volume,
                sell_volume,
                volume_imbalance
            FROM coinbase_bars
            WHERE product_id = ?
              AND interval_seconds = ?
            ORDER BY start_time DESC
            LIMIT 1
            """,
            (product_id, interval_seconds),
        ).fetchone()

    return {
        "trade_count": int(trade_row["trade_count"]),
        "latest_trade_time": trade_row["latest_trade_time"],
        "latest_trade": (
            dict(latest_trade_row)
            if latest_trade_row is not None
            else None
        ),
        "bar_count": int(bar_count_row["bar_count"]),
        "latest_bar": (
            dict(latest_bar_row)
            if latest_bar_row is not None
            else None
        ),
    }


def recent_bars(
    product_id: str = "BTC-USD",
    interval_seconds: int = 60,
    limit: int = 300,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """Load recent OHLCV bars in chronological order."""
    initialize_bar_store(db_path)

    with database_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                start_time,
                end_time,
                open,
                high,
                low,
                close,
                volume,
                trade_count,
                buy_volume,
                sell_volume,
                volume_imbalance
            FROM coinbase_bars
            WHERE product_id = ?
              AND interval_seconds = ?
            ORDER BY start_time DESC
            LIMIT ?
            """,
            (product_id, interval_seconds, limit),
        ).fetchall()

    dataframe = pd.DataFrame([dict(row) for row in rows])

    if dataframe.empty:
        return dataframe

    dataframe = dataframe.iloc[::-1].reset_index(drop=True)
    dataframe["start_time"] = pd.to_datetime(
        dataframe["start_time"],
        utc=True,
    )
    dataframe["end_time"] = pd.to_datetime(
        dataframe["end_time"],
        utc=True,
    )

    return dataframe


def recent_trades(
    product_id: str = "BTC-USD",
    limit: int = 200,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """Load recent Coinbase trades, newest first."""
    initialize_trade_store(db_path)

    with database_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                timestamp,
                trade_id,
                price,
                size,
                side
            FROM coinbase_trades
            WHERE product_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (product_id, limit),
        ).fetchall()

    dataframe = pd.DataFrame([dict(row) for row in rows])

    if not dataframe.empty:
        dataframe["timestamp"] = pd.to_datetime(
            dataframe["timestamp"],
            utc=True,
        )

    return dataframe
