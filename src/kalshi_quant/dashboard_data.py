from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .bars import initialize_bar_store
from .db import DEFAULT_DB_PATH, database_connection
from .market_discovery import (
    current_market_selection as load_current_market_selection,
    recent_market_selections as load_market_selections,
)
from .paper_trade_lifecycle import (
    paper_bankroll_history as load_bankroll_history,
    paper_trade_summary as load_paper_trade_summary,
    recent_paper_trades as load_paper_trades,
)
from .paper_trade_store import (
    recent_paper_decisions as load_paper_decisions,
)
from .signal_store import recent_market_signals
from .trade_store import initialize_trade_store


def market_summary(
    product_id: str = "BTC-USD",
    interval_seconds: int = 60,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
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


def recent_signal_history(
    product_id: str = "BTC-USD",
    interval_seconds: int = 5,
    limit: int = 200,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    rows = recent_market_signals(
        product_id=product_id,
        interval_seconds=interval_seconds,
        limit=limit,
        db_path=db_path,
    )

    dataframe = pd.DataFrame(rows)

    if dataframe.empty:
        return dataframe

    dataframe = dataframe.iloc[::-1].reset_index(drop=True)
    dataframe["timestamp"] = pd.to_datetime(
        dataframe["timestamp"],
        utc=True,
    )

    numeric_columns = [
        "score",
        "probability_up",
        "confidence",
        "trend_score",
        "momentum_score",
        "vwap_score",
        "rsi_score",
        "order_flow_score",
        "order_flow_imbalance",
        "order_flow_reliability",
        "timeframe_agreement",
    ]

    for column in numeric_columns:
        if column in dataframe.columns:
            dataframe[column] = pd.to_numeric(
                dataframe[column],
                errors="coerce",
            )

    return dataframe


def paper_trading_summary(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    starting_bankroll: float = 1000.0,
) -> dict[str, Any]:
    return load_paper_trade_summary(
        db_path,
        starting_bankroll=starting_bankroll,
    )


def recent_paper_decisions(
    limit: int = 200,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    dataframe = pd.DataFrame(
        load_paper_decisions(
            limit=limit,
            db_path=db_path,
        )
    )

    if not dataframe.empty:
        dataframe["signal_timestamp"] = pd.to_datetime(
            dataframe["signal_timestamp"],
            utc=True,
        )
        dataframe["evaluated_at"] = pd.to_datetime(
            dataframe["evaluated_at"],
            utc=True,
        )

    return dataframe


def recent_paper_trades(
    limit: int = 200,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    dataframe = pd.DataFrame(
        load_paper_trades(
            limit=limit,
            db_path=db_path,
        )
    )

    if not dataframe.empty:
        dataframe["opened_at"] = pd.to_datetime(
            dataframe["opened_at"],
            utc=True,
        )
        dataframe["closed_at"] = pd.to_datetime(
            dataframe["closed_at"],
            utc=True,
            errors="coerce",
        )

        numeric_columns = [
            "entry_price",
            "model_probability",
            "edge",
            "contracts",
            "stake",
            "won",
            "pnl",
            "payout_per_contract",
            "gross_payout",
            "bankroll_before",
            "bankroll_after",
            "peak_bankroll",
            "drawdown",
        ]

        for column in numeric_columns:
            if column in dataframe.columns:
                dataframe[column] = pd.to_numeric(
                    dataframe[column],
                    errors="coerce",
                )

    return dataframe


def paper_bankroll_history(
    limit: int = 1000,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    dataframe = pd.DataFrame(
        load_bankroll_history(
            limit=limit,
            db_path=db_path,
        )
    )

    if not dataframe.empty:
        dataframe["settled_at"] = pd.to_datetime(
            dataframe["settled_at"],
            utc=True,
        )

        numeric_columns = [
            "entry_price",
            "contracts",
            "stake",
            "gross_payout",
            "pnl",
            "bankroll_before",
            "bankroll_after",
            "peak_bankroll",
            "drawdown",
            "won",
        ]

        for column in numeric_columns:
            if column in dataframe.columns:
                dataframe[column] = pd.to_numeric(
                    dataframe[column],
                    errors="coerce",
                )

    return dataframe

def current_market_selection(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    return load_current_market_selection(
        db_path=db_path,
    )


def recent_market_selections(
    limit: int = 200,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    dataframe = pd.DataFrame(
        load_market_selections(
            limit=limit,
            db_path=db_path,
        )
    )

    if dataframe.empty:
        return dataframe

    dataframe["selected_at"] = pd.to_datetime(
        dataframe["selected_at"],
        utc=True,
    )

    numeric_columns = [
        "target_price",
        "btc_price",
        "seconds_remaining",
        "yes_bid",
        "yes_ask",
        "no_bid",
        "no_ask",
        "spread",
        "volume",
        "open_interest",
        "rollover",
    ]

    for column in numeric_columns:
        if column in dataframe.columns:
            dataframe[column] = pd.to_numeric(
                dataframe[column],
                errors="coerce",
            )

    return dataframe

