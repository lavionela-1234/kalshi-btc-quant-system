from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import (
    DEFAULT_DB_PATH,
    database_connection,
    initialize_database,
    utc_now,
)


PAPER_DECISION_SCHEMA = '''
CREATE TABLE IF NOT EXISTS paper_trade_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_ticker TEXT NOT NULL,
    signal_timestamp TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,

    technical_direction TEXT NOT NULL,
    technical_action TEXT NOT NULL,
    technical_score REAL NOT NULL,
    technical_probability_up REAL NOT NULL,
    technical_confidence REAL NOT NULL,

    btc_price REAL NOT NULL,
    target_price REAL NOT NULL,
    seconds_remaining REAL NOT NULL,

    yes_bid REAL,
    yes_ask REAL,
    no_bid REAL,
    no_ask REAL,
    spread REAL,

    decision TEXT NOT NULL,
    side TEXT,
    edge REAL NOT NULL,
    contracts INTEGER NOT NULL,
    stake REAL NOT NULL,
    reason TEXT NOT NULL,

    paper_trade_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(market_ticker, signal_timestamp),
    FOREIGN KEY (market_ticker) REFERENCES markets(ticker),
    FOREIGN KEY (paper_trade_id) REFERENCES paper_trades(id)
);

CREATE INDEX IF NOT EXISTS idx_paper_trade_decisions_lookup
ON paper_trade_decisions(
    market_ticker,
    signal_timestamp
);
'''


@dataclass(frozen=True)
class PaperDecisionRecord:
    market_ticker: str
    signal_timestamp: str
    technical_direction: str
    technical_action: str
    technical_score: float
    technical_probability_up: float
    technical_confidence: float
    btc_price: float
    target_price: float
    seconds_remaining: float
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    spread: float | None
    decision: str
    side: str | None
    edge: float
    contracts: int
    stake: float
    reason: str


@dataclass(frozen=True)
class PaperDecisionSaveResult:
    created: bool
    decision_id: int | None
    paper_trade_id: int | None


def initialize_paper_trade_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Path:
    path = initialize_database(db_path)

    with database_connection(path) as connection:
        connection.executescript(PAPER_DECISION_SCHEMA)

    return path


def paper_decision_exists(
    *,
    market_ticker: str,
    signal_timestamp: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    initialize_paper_trade_store(db_path)

    with database_connection(db_path) as connection:
        row = connection.execute(
            '''
            SELECT 1
            FROM paper_trade_decisions
            WHERE market_ticker = ?
              AND signal_timestamp = ?
            LIMIT 1
            ''',
            (market_ticker, signal_timestamp),
        ).fetchone()

    return row is not None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def save_paper_decision(
    record: PaperDecisionRecord,
    *,
    market: dict[str, Any],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> PaperDecisionSaveResult:
    initialize_paper_trade_store(db_path)

    now = utc_now()
    title = (
        market.get("title")
        or market.get("subtitle")
        or record.market_ticker
    )
    open_time = (
        market.get("open_time")
        or market.get("expected_expiration_time")
    )
    close_time = (
        market.get("close_time")
        or market.get("expected_expiration_time")
    )
    status = market.get("status")
    settlement_value = _float_or_none(
        market.get("settlement_value")
    )

    settled_up_raw = market.get("settled_up")
    settled_up = (
        int(bool(settled_up_raw))
        if settled_up_raw is not None
        else None
    )

    with database_connection(db_path) as connection:
        existing = connection.execute(
            '''
            SELECT id, paper_trade_id
            FROM paper_trade_decisions
            WHERE market_ticker = ?
              AND signal_timestamp = ?
            LIMIT 1
            ''',
            (
                record.market_ticker,
                record.signal_timestamp,
            ),
        ).fetchone()

        if existing is not None:
            return PaperDecisionSaveResult(
                created=False,
                decision_id=int(existing["id"]),
                paper_trade_id=(
                    int(existing["paper_trade_id"])
                    if existing["paper_trade_id"] is not None
                    else None
                ),
            )

        connection.execute(
            '''
            INSERT INTO markets (
                ticker,
                title,
                target_price,
                open_time,
                close_time,
                status,
                settlement_value,
                settled_up,
                raw_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            ON CONFLICT(ticker)
            DO UPDATE SET
                title = excluded.title,
                target_price = excluded.target_price,
                open_time = excluded.open_time,
                close_time = excluded.close_time,
                status = excluded.status,
                settlement_value = excluded.settlement_value,
                settled_up = excluded.settled_up,
                updated_at = excluded.updated_at
            ''',
            (
                record.market_ticker,
                str(title),
                record.target_price,
                open_time,
                close_time,
                status,
                settlement_value,
                settled_up,
                now,
                now,
            ),
        )

        paper_trade_id: int | None = None

        if (
            record.decision == "OPEN"
            and record.side in {"YES", "NO"}
            and record.contracts > 0
            and record.stake > 0
        ):
            ask = (
                record.yes_ask
                if record.side == "YES"
                else record.no_ask
            )

            cursor = connection.execute(
                '''
                INSERT INTO paper_trades (
                    market_ticker,
                    opened_at,
                    side,
                    entry_price,
                    model_probability,
                    edge,
                    contracts,
                    stake,
                    status,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
                ''',
                (
                    record.market_ticker,
                    record.signal_timestamp,
                    record.side,
                    float(ask),
                    record.technical_probability_up,
                    record.edge,
                    record.contracts,
                    record.stake,
                    record.reason,
                ),
            )
            paper_trade_id = int(cursor.lastrowid)

        cursor = connection.execute(
            '''
            INSERT INTO paper_trade_decisions (
                market_ticker,
                signal_timestamp,
                evaluated_at,
                technical_direction,
                technical_action,
                technical_score,
                technical_probability_up,
                technical_confidence,
                btc_price,
                target_price,
                seconds_remaining,
                yes_bid,
                yes_ask,
                no_bid,
                no_ask,
                spread,
                decision,
                side,
                edge,
                contracts,
                stake,
                reason,
                paper_trade_id
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ''',
            (
                record.market_ticker,
                record.signal_timestamp,
                now,
                record.technical_direction,
                record.technical_action,
                record.technical_score,
                record.technical_probability_up,
                record.technical_confidence,
                record.btc_price,
                record.target_price,
                record.seconds_remaining,
                record.yes_bid,
                record.yes_ask,
                record.no_bid,
                record.no_ask,
                record.spread,
                record.decision,
                record.side,
                record.edge,
                record.contracts,
                record.stake,
                record.reason,
                paper_trade_id,
            ),
        )

        return PaperDecisionSaveResult(
            created=True,
            decision_id=int(cursor.lastrowid),
            paper_trade_id=paper_trade_id,
        )



def _parse_utc_timestamp(value: str) -> datetime:
    normalized = str(value).replace("Z", "+00:00")
    timestamp = datetime.fromisoformat(normalized)

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(timezone.utc)


def paper_entry_block_reason(
    *,
    market_ticker: str,
    side: str,
    signal_timestamp: str,
    minimum_confidence: float,
    episode_gap_seconds: float,
    cooldown_seconds: float,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> str | None:
    """Return a restart-safe reason that blocks a repeated paper entry."""

    if side not in {"YES", "NO"}:
        raise ValueError("side must be YES or NO")

    if episode_gap_seconds < 0:
        raise ValueError(
            "episode_gap_seconds must be zero or greater"
        )

    if cooldown_seconds < 0:
        raise ValueError(
            "cooldown_seconds must be zero or greater"
        )

    initialize_paper_trade_store(db_path)
    current_time = _parse_utc_timestamp(signal_timestamp)
    expected_action = (
        "LONG_BIAS"
        if side == "YES"
        else "SHORT_BIAS"
    )

    with database_connection(db_path) as connection:
        open_trade = connection.execute(
            """
            SELECT id
            FROM paper_trades
            WHERE market_ticker = ?
              AND side = ?
              AND status = 'OPEN'
            ORDER BY opened_at DESC, id DESC
            LIMIT 1
            """,
            (market_ticker, side),
        ).fetchone()

        if open_trade is not None:
            return "OPEN_POSITION"

        if cooldown_seconds > 0:
            latest_closed = connection.execute(
                """
                SELECT closed_at
                FROM paper_trades
                WHERE market_ticker = ?
                  AND side = ?
                  AND status != 'OPEN'
                  AND closed_at IS NOT NULL
                ORDER BY closed_at DESC, id DESC
                LIMIT 1
                """,
                (market_ticker, side),
            ).fetchone()

            if latest_closed is not None:
                closed_time = _parse_utc_timestamp(
                    str(latest_closed["closed_at"])
                )
                elapsed = (
                    current_time - closed_time
                ).total_seconds()

                if 0 <= elapsed < cooldown_seconds:
                    return "COOLDOWN"

        latest_open_decision = connection.execute(
            """
            SELECT id, signal_timestamp
            FROM paper_trade_decisions
            WHERE market_ticker = ?
              AND side = ?
              AND decision = 'OPEN'
            ORDER BY id DESC
            LIMIT 1
            """,
            (market_ticker, side),
        ).fetchone()

        if latest_open_decision is None:
            return None

        previous_time = _parse_utc_timestamp(
            str(latest_open_decision["signal_timestamp"])
        )

        later_decisions = connection.execute(
            """
            SELECT
                signal_timestamp,
                technical_action,
                technical_confidence
            FROM paper_trade_decisions
            WHERE market_ticker = ?
              AND id > ?
            ORDER BY id
            """,
            (
                market_ticker,
                int(latest_open_decision["id"]),
            ),
        ).fetchall()

    for decision in later_decisions:
        decision_time = _parse_utc_timestamp(
            str(decision["signal_timestamp"])
        )
        gap = (decision_time - previous_time).total_seconds()

        if (
            decision["technical_action"] != expected_action
            or float(decision["technical_confidence"])
            < minimum_confidence
            or gap < 0
            or gap > episode_gap_seconds
        ):
            return None

        previous_time = decision_time

    current_gap = (
        current_time - previous_time
    ).total_seconds()

    if 0 <= current_gap <= episode_gap_seconds:
        return "ACTIVE_EPISODE"

    return None

def paper_trade_summary(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    initialize_paper_trade_store(db_path)

    with database_connection(db_path) as connection:
        trade_row = connection.execute(
            '''
            SELECT
                COUNT(*) AS total_trades,
                SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END)
                    AS open_trades,
                COALESCE(SUM(stake), 0) AS total_stake,
                COALESCE(SUM(
                    CASE WHEN status != 'OPEN' THEN pnl ELSE 0 END
                ), 0) AS realized_pnl
            FROM paper_trades
            '''
        ).fetchone()

        decision_row = connection.execute(
            '''
            SELECT
                COUNT(*) AS total_decisions,
                SUM(CASE WHEN decision = 'OPEN' THEN 1 ELSE 0 END)
                    AS open_decisions,
                SUM(CASE WHEN decision = 'SKIP' THEN 1 ELSE 0 END)
                    AS skipped_decisions,
                SUM(CASE WHEN decision = 'BLOCKED' THEN 1 ELSE 0 END)
                    AS blocked_decisions
            FROM paper_trade_decisions
            '''
        ).fetchone()

    return {
        "total_trades": int(trade_row["total_trades"] or 0),
        "open_trades": int(trade_row["open_trades"] or 0),
        "total_stake": float(trade_row["total_stake"] or 0),
        "realized_pnl": float(trade_row["realized_pnl"] or 0),
        "total_decisions": int(
            decision_row["total_decisions"] or 0
        ),
        "open_decisions": int(
            decision_row["open_decisions"] or 0
        ),
        "skipped_decisions": int(
            decision_row["skipped_decisions"] or 0
        ),
        "blocked_decisions": int(
            decision_row["blocked_decisions"] or 0
        ),
    }


def paper_entry_diagnostics(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    min_confidence: float = 0.25,
    max_spread: float = 0.08,
    min_seconds: float = 10.0,
    max_seconds: float = 300.0,
    min_edge: float = 0.02,
) -> list[dict[str, Any]]:
    """Summarize sequential paper-entry gate performance."""

    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(
            "min_confidence must be between zero and one"
        )
    if max_spread < 0.0:
        raise ValueError("max_spread must not be negative")
    if min_seconds < 0.0:
        raise ValueError("min_seconds must not be negative")
    if max_seconds < min_seconds:
        raise ValueError(
            "max_seconds must be greater than or equal to min_seconds"
        )
    if min_edge < 0.0:
        raise ValueError("min_edge must not be negative")

    initialize_paper_trade_store(db_path)

    with database_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                technical_action,
                technical_confidence,
                seconds_remaining,
                yes_ask,
                no_ask,
                spread,
                decision,
                side,
                edge
            FROM paper_trade_decisions
            ORDER BY signal_timestamp, id
            """
        ).fetchall()

    gate_order = [
        "Technical action",
        "Confidence",
        "Order book",
        "Spread",
        "Time window",
        "Expected edge",
        "Direction alignment",
        "Risk controls",
    ]

    thresholds = {
        "Technical action": "LONG_BIAS or SHORT_BIAS",
        "Confidence": f">= {min_confidence:.1%}",
        "Order book": "YES and NO asks available",
        "Spread": f"<= {max_spread:.1%}",
        "Time window": (
            f"{min_seconds:.0f}s to {max_seconds:.0f}s remaining"
        ),
        "Expected edge": f">= {min_edge:.1%}",
        "Direction alignment": (
            "Kalshi edge side matches technical bias"
        ),
        "Risk controls": "Daily-loss and Kelly controls pass",
    }

    counts = {
        gate: {
            "evaluated": 0,
            "passed": 0,
            "failed": 0,
        }
        for gate in gate_order
    }

    def record(gate: str, passed: bool) -> bool:
        counts[gate]["evaluated"] += 1

        if passed:
            counts[gate]["passed"] += 1
        else:
            counts[gate]["failed"] += 1

        return passed

    for row in rows:
        technical_action = str(row["technical_action"])

        if not record(
            "Technical action",
            technical_action in {"LONG_BIAS", "SHORT_BIAS"},
        ):
            continue

        if not record(
            "Confidence",
            float(row["technical_confidence"]) >= min_confidence,
        ):
            continue

        if not record(
            "Order book",
            row["yes_ask"] is not None
            and row["no_ask"] is not None,
        ):
            continue

        spread = row["spread"]

        if not record(
            "Spread",
            spread is not None
            and float(spread) <= max_spread,
        ):
            continue

        seconds_remaining = float(row["seconds_remaining"])

        if not record(
            "Time window",
            min_seconds
            <= seconds_remaining
            <= max_seconds,
        ):
            continue

        if not record(
            "Expected edge",
            float(row["edge"]) >= min_edge,
        ):
            continue

        expected_side = (
            "YES"
            if technical_action == "LONG_BIAS"
            else "NO"
        )

        if not record(
            "Direction alignment",
            row["side"] == expected_side,
        ):
            continue

        record(
            "Risk controls",
            row["decision"] == "OPEN",
        )

    total_decisions = len(rows)
    diagnostics: list[dict[str, Any]] = []

    for gate in gate_order:
        evaluated = counts[gate]["evaluated"]
        passed = counts[gate]["passed"]
        failed = counts[gate]["failed"]

        diagnostics.append(
            {
                "gate": gate,
                "threshold": thresholds[gate],
                "total_decisions": total_decisions,
                "evaluated": evaluated,
                "not_evaluated": total_decisions - evaluated,
                "passed": passed,
                "failed": failed,
                "pass_rate": (
                    passed / evaluated
                    if evaluated
                    else 0.0
                ),
            }
        )

    return diagnostics


def recent_paper_decisions(
    *,
    limit: int = 200,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    initialize_paper_trade_store(db_path)

    with database_connection(db_path) as connection:
        rows = connection.execute(
            '''
            SELECT
                market_ticker,
                signal_timestamp,
                evaluated_at,
                technical_direction,
                technical_action,
                technical_score,
                technical_probability_up,
                technical_confidence,
                btc_price,
                target_price,
                seconds_remaining,
                yes_bid,
                yes_ask,
                no_bid,
                no_ask,
                spread,
                decision,
                side,
                edge,
                contracts,
                stake,
                reason,
                paper_trade_id
            FROM paper_trade_decisions
            ORDER BY signal_timestamp DESC, id DESC
            LIMIT ?
            ''',
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def recent_paper_trades(
    *,
    limit: int = 200,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    initialize_paper_trade_store(db_path)

    with database_connection(db_path) as connection:
        rows = connection.execute(
            '''
            SELECT
                id,
                market_ticker,
                opened_at,
                side,
                entry_price,
                model_probability,
                edge,
                contracts,
                stake,
                status,
                closed_at,
                won,
                pnl,
                notes
            FROM paper_trades
            ORDER BY opened_at DESC, id DESC
            LIMIT ?
            ''',
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def realized_pnl_today(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> float:
    initialize_paper_trade_store(db_path)

    today = datetime.now(timezone.utc).date().isoformat()

    with database_connection(db_path) as connection:
        row = connection.execute(
            '''
            SELECT COALESCE(SUM(pnl), 0) AS pnl
            FROM paper_trades
            WHERE status != 'OPEN'
              AND substr(COALESCE(closed_at, opened_at), 1, 10) = ?
            ''',
            (today,),
        ).fetchone()

    return float(row["pnl"] or 0)
