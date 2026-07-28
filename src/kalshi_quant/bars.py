from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .db import DEFAULT_DB_PATH, database_connection
from .trade_store import initialize_trade_store


BAR_SCHEMA = """
CREATE TABLE IF NOT EXISTS coinbase_bars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,

    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,

    volume REAL NOT NULL,
    trade_count INTEGER NOT NULL,
    buy_volume REAL NOT NULL,
    sell_volume REAL NOT NULL,
    volume_imbalance REAL NOT NULL,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(product_id, interval_seconds, start_time)
);

CREATE INDEX IF NOT EXISTS idx_coinbase_bars_lookup
ON coinbase_bars(product_id, interval_seconds, start_time);
"""


@dataclass
class MarketBar:
    """One aggregated Coinbase market-data bar."""

    product_id: str
    interval_seconds: int
    start_time: str
    end_time: str

    open: float
    high: float
    low: float
    close: float

    volume: float
    trade_count: int
    buy_volume: float
    sell_volume: float
    volume_imbalance: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "interval_seconds": self.interval_seconds,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "trade_count": self.trade_count,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "volume_imbalance": self.volume_imbalance,
        }


def initialize_bar_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Path:
    """Create the market-bar table and indexes."""
    path = Path(db_path)

    with database_connection(path) as connection:
        connection.executescript(BAR_SCHEMA)

    return path


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC."""
    normalized = value.strip()

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    timestamp = datetime.fromisoformat(normalized)

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(timezone.utc)


def iso_timestamp(value: datetime) -> str:
    """Return a UTC ISO-8601 timestamp ending in Z."""
    utc_value = value.astimezone(timezone.utc)
    return utc_value.isoformat().replace("+00:00", "Z")


def floor_timestamp(
    timestamp: datetime,
    interval_seconds: int,
) -> datetime:
    """Round a timestamp down to the beginning of its bar interval."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")

    epoch_seconds = int(timestamp.timestamp())
    floored_seconds = (
        epoch_seconds // interval_seconds
    ) * interval_seconds

    return datetime.fromtimestamp(
        floored_seconds,
        tz=timezone.utc,
    )


def calculate_volume_imbalance(
    buy_volume: float,
    sell_volume: float,
) -> float:
    """
    Calculate normalized volume imbalance.

    The result ranges from -1 to +1:

    +1 = all buy volume
    -1 = all sell volume
     0 = balanced volume
    """
    total_directional_volume = buy_volume + sell_volume

    if total_directional_volume == 0:
        return 0.0

    return (
        buy_volume - sell_volume
    ) / total_directional_volume


def aggregate_trades(
    trades: Iterable[dict[str, Any]],
    interval_seconds: int,
) -> list[MarketBar]:
    """Aggregate normalized Coinbase trades into market bars."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")

    ordered_trades = sorted(
        trades,
        key=lambda trade: parse_timestamp(str(trade["timestamp"])),
    )

    grouped: dict[
        tuple[str, datetime],
        list[dict[str, Any]],
    ] = {}

    for trade in ordered_trades:
        product_id = str(trade["product_id"])
        timestamp = parse_timestamp(str(trade["timestamp"]))
        bar_start = floor_timestamp(
            timestamp,
            interval_seconds,
        )

        grouped.setdefault(
            (product_id, bar_start),
            [],
        ).append(trade)

    bars: list[MarketBar] = []

    for (product_id, bar_start), group in sorted(
        grouped.items(),
        key=lambda item: item[0][1],
    ):
        prices = [float(trade["price"]) for trade in group]
        sizes = [float(trade["size"]) for trade in group]

        buy_volume = sum(
            float(trade["size"])
            for trade in group
            if str(trade.get("side", "")).upper() == "BUY"
        )

        sell_volume = sum(
            float(trade["size"])
            for trade in group
            if str(trade.get("side", "")).upper() == "SELL"
        )

        bar_end = datetime.fromtimestamp(
            bar_start.timestamp() + interval_seconds,
            tz=timezone.utc,
        )

        bars.append(
            MarketBar(
                product_id=product_id,
                interval_seconds=interval_seconds,
                start_time=iso_timestamp(bar_start),
                end_time=iso_timestamp(bar_end),
                open=prices[0],
                high=max(prices),
                low=min(prices),
                close=prices[-1],
                volume=sum(sizes),
                trade_count=len(group),
                buy_volume=buy_volume,
                sell_volume=sell_volume,
                volume_imbalance=calculate_volume_imbalance(
                    buy_volume,
                    sell_volume,
                ),
            )
        )

    return bars


def load_coinbase_trades(
    product_id: str = "BTC-USD",
    db_path: str | Path = DEFAULT_DB_PATH,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Load recorded Coinbase trades in chronological order."""
    initialize_trade_store(db_path)

    parameters: list[Any] = [product_id]

    if limit is None:
        query = """
            SELECT
                trade_id,
                product_id,
                timestamp,
                price,
                size,
                side
            FROM coinbase_trades
            WHERE product_id = ?
            ORDER BY timestamp ASC, id ASC
        """
    else:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        query = """
            SELECT *
            FROM (
                SELECT
                    id,
                    trade_id,
                    product_id,
                    timestamp,
                    price,
                    size,
                    side
                FROM coinbase_trades
                WHERE product_id = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
            )
            ORDER BY timestamp ASC, id ASC
        """

        parameters.append(limit)

    with database_connection(db_path) as connection:
        rows = connection.execute(
            query,
            parameters,
        ).fetchall()

    return [dict(row) for row in rows]


def save_market_bar(
    bar: MarketBar,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    """Insert or update one market bar."""
    initialize_bar_store(db_path)

    with database_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO coinbase_bars (
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
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(
                product_id,
                interval_seconds,
                start_time
            )
            DO UPDATE SET
                end_time = excluded.end_time,
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                trade_count = excluded.trade_count,
                buy_volume = excluded.buy_volume,
                sell_volume = excluded.sell_volume,
                volume_imbalance = excluded.volume_imbalance,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                bar.product_id,
                bar.interval_seconds,
                bar.start_time,
                bar.end_time,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.trade_count,
                bar.buy_volume,
                bar.sell_volume,
                bar.volume_imbalance,
            ),
        )


def build_bars_from_database(
    interval_seconds: int,
    product_id: str = "BTC-USD",
    db_path: str | Path = DEFAULT_DB_PATH,
    trade_limit: int | None = None,
) -> int:
    """Build and save bars from recorded Coinbase trades."""
    trades = load_coinbase_trades(
        product_id=product_id,
        db_path=db_path,
        limit=trade_limit,
    )

    bars = aggregate_trades(
        trades=trades,
        interval_seconds=interval_seconds,
    )

    for bar in bars:
        save_market_bar(
            bar=bar,
            db_path=db_path,
        )

    return len(bars)


def bar_count(
    interval_seconds: int | None = None,
    product_id: str = "BTC-USD",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """Return the number of stored market bars."""
    initialize_bar_store(db_path)

    with database_connection(db_path) as connection:
        if interval_seconds is None:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM coinbase_bars
                WHERE product_id = ?
                """,
                (product_id,),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM coinbase_bars
                WHERE product_id = ?
                  AND interval_seconds = ?
                """,
                (
                    product_id,
                    interval_seconds,
                ),
            ).fetchone()

    return int(row["count"])


def latest_bar(
    interval_seconds: int,
    product_id: str = "BTC-USD",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Return the latest stored market bar."""
    initialize_bar_store(db_path)

    with database_connection(db_path) as connection:
        row = connection.execute(
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
            (
                product_id,
                interval_seconds,
            ),
        ).fetchone()

    return dict(row) if row is not None else None