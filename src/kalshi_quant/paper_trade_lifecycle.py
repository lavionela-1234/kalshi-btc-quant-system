from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import Settings
from .db import (
    DEFAULT_DB_PATH,
    database_connection,
    initialize_database,
    utc_now,
)
from .kalshi import KalshiREST
from .paper_trade_store import initialize_paper_trade_store


SETTLEMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_trade_settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_trade_id INTEGER NOT NULL UNIQUE,
    market_ticker TEXT NOT NULL,
    settled_at TEXT NOT NULL,
    market_result TEXT NOT NULL CHECK(
        market_result IN ('YES', 'NO')
    ),
    payout_per_contract REAL NOT NULL,
    gross_payout REAL NOT NULL,
    pnl REAL NOT NULL,
    bankroll_before REAL NOT NULL,
    bankroll_after REAL NOT NULL,
    peak_bankroll REAL NOT NULL,
    drawdown REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (paper_trade_id) REFERENCES paper_trades(id),
    FOREIGN KEY (market_ticker) REFERENCES markets(ticker)
);

CREATE INDEX IF NOT EXISTS idx_paper_trade_settlements_time
ON paper_trade_settlements(
    settled_at,
    id
);
"""


@dataclass(frozen=True)
class PaperSettlementSaveResult:
    created: bool
    settlement_id: int | None
    paper_trade_id: int
    market_ticker: str
    side: str
    market_result: str
    won: bool
    pnl: float
    bankroll_before: float
    bankroll_after: float
    peak_bankroll: float
    drawdown: float
    reason: str


@dataclass(frozen=True)
class SettlementBatchResult:
    checked_markets: int
    open_trades: int
    settled: int
    pending: int
    duplicates: int
    errors: int
    outcomes: tuple[PaperSettlementSaveResult, ...]


class SettlementMarketClient(Protocol):
    def market(self, ticker: str) -> dict[str, Any]:
        ...


def initialize_settlement_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Path:
    path = initialize_paper_trade_store(db_path)

    with database_connection(path) as connection:
        connection.executescript(SETTLEMENT_SCHEMA)

    return path


def _normalized_result(value: Any) -> str | None:
    result = str(value or "").strip().upper()

    if result in {"YES", "NO"}:
        return result

    return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def record_market_state(
    market: dict[str, Any],
    *,
    fallback_ticker: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    initialize_settlement_store(db_path)

    ticker = str(
        market.get("ticker")
        or fallback_ticker
        or ""
    ).strip()

    if not ticker:
        raise ValueError("Market ticker is required")

    result = _normalized_result(
        market.get("result")
        or market.get("market_result")
    )
    target_price = _float_or_none(
        market.get("target_price")
        or market.get("floor_strike")
        or market.get("cap_strike")
        or market.get("strike")
    )
    settlement_value = _float_or_none(
        market.get("settlement_value_dollars")
        or market.get("settlement_value")
    )
    title = (
        market.get("title")
        or market.get("subtitle")
        or market.get("yes_sub_title")
        or ticker
    )
    close_time = (
        market.get("close_time")
        or market.get("latest_expiration_time")
        or market.get("expected_expiration_time")
    )
    now = utc_now()

    with database_connection(db_path) as connection:
        connection.execute(
            """
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker)
            DO UPDATE SET
                title = COALESCE(excluded.title, title),
                target_price = COALESCE(
                    excluded.target_price,
                    target_price
                ),
                open_time = COALESCE(
                    excluded.open_time,
                    open_time
                ),
                close_time = COALESCE(
                    excluded.close_time,
                    close_time
                ),
                status = COALESCE(
                    excluded.status,
                    status
                ),
                settlement_value = COALESCE(
                    excluded.settlement_value,
                    settlement_value
                ),
                settled_up = COALESCE(
                    excluded.settled_up,
                    settled_up
                ),
                raw_json = excluded.raw_json,
                updated_at = excluded.updated_at
            """,
            (
                ticker,
                str(title),
                target_price,
                market.get("open_time"),
                close_time,
                market.get("status"),
                settlement_value,
                (
                    1
                    if result == "YES"
                    else 0
                    if result == "NO"
                    else None
                ),
                json.dumps(market, default=str),
                now,
                now,
            ),
        )


def open_paper_trades(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    initialize_settlement_store(db_path)

    with database_connection(db_path) as connection:
        rows = connection.execute(
            """
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
                notes
            FROM paper_trades
            WHERE status = 'OPEN'
            ORDER BY opened_at, id
            """
        ).fetchall()

    return [dict(row) for row in rows]


def settle_paper_trade(
    *,
    paper_trade_id: int,
    market_result: str,
    starting_bankroll: float,
    settled_at: str | None = None,
    market: dict[str, Any] | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> PaperSettlementSaveResult:
    if starting_bankroll <= 0:
        raise ValueError(
            "starting_bankroll must be greater than zero"
        )

    result = _normalized_result(market_result)

    if result is None:
        raise ValueError("market_result must be YES or NO")

    initialize_settlement_store(db_path)
    closed_at = settled_at or utc_now()

    with database_connection(db_path) as connection:
        trade = connection.execute(
            """
            SELECT
                id,
                market_ticker,
                side,
                contracts,
                stake,
                status,
                won,
                pnl
            FROM paper_trades
            WHERE id = ?
            LIMIT 1
            """,
            (paper_trade_id,),
        ).fetchone()

        if trade is None:
            raise ValueError(
                f"Paper trade {paper_trade_id} does not exist"
            )

        existing = connection.execute(
            """
            SELECT
                id,
                market_result,
                pnl,
                bankroll_before,
                bankroll_after,
                peak_bankroll,
                drawdown
            FROM paper_trade_settlements
            WHERE paper_trade_id = ?
            LIMIT 1
            """,
            (paper_trade_id,),
        ).fetchone()

        side = str(trade["side"]).upper()
        ticker = str(trade["market_ticker"])

        if existing is not None or trade["status"] != "OPEN":
            existing_result = (
                str(existing["market_result"])
                if existing is not None
                else result
            )
            existing_pnl = (
                float(existing["pnl"])
                if existing is not None
                else float(trade["pnl"] or 0)
            )
            bankroll_before = (
                float(existing["bankroll_before"])
                if existing is not None
                else starting_bankroll
            )
            bankroll_after = (
                float(existing["bankroll_after"])
                if existing is not None
                else starting_bankroll + existing_pnl
            )
            peak_bankroll = (
                float(existing["peak_bankroll"])
                if existing is not None
                else max(
                    starting_bankroll,
                    bankroll_after,
                )
            )
            drawdown = (
                float(existing["drawdown"])
                if existing is not None
                else 0.0
            )

            return PaperSettlementSaveResult(
                created=False,
                settlement_id=(
                    int(existing["id"])
                    if existing is not None
                    else None
                ),
                paper_trade_id=paper_trade_id,
                market_ticker=ticker,
                side=side,
                market_result=existing_result,
                won=bool(trade["won"]),
                pnl=existing_pnl,
                bankroll_before=bankroll_before,
                bankroll_after=bankroll_after,
                peak_bankroll=peak_bankroll,
                drawdown=drawdown,
                reason="Paper trade was already settled",
            )

        totals = connection.execute(
            """
            SELECT
                COALESCE(SUM(pnl), 0) AS total_pnl,
                COALESCE(MAX(bankroll_after), ?)
                    AS peak_bankroll
            FROM paper_trade_settlements
            """,
            (starting_bankroll,),
        ).fetchone()

        prior_pnl = float(totals["total_pnl"] or 0)
        prior_peak = max(
            starting_bankroll,
            float(totals["peak_bankroll"]),
        )
        bankroll_before = starting_bankroll + prior_pnl

        won = side == result
        payout_per_contract = 1.0 if won else 0.0
        gross_payout = (
            int(trade["contracts"])
            * payout_per_contract
        )
        pnl = gross_payout - float(trade["stake"])
        bankroll_after = bankroll_before + pnl
        peak_bankroll = max(
            prior_peak,
            bankroll_before,
            bankroll_after,
        )
        drawdown = (
            (bankroll_after - peak_bankroll)
            / peak_bankroll
            if peak_bankroll > 0
            else 0.0
        )

        cursor = connection.execute(
            """
            INSERT INTO paper_trade_settlements (
                paper_trade_id,
                market_ticker,
                settled_at,
                market_result,
                payout_per_contract,
                gross_payout,
                pnl,
                bankroll_before,
                bankroll_after,
                peak_bankroll,
                drawdown
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_trade_id,
                ticker,
                closed_at,
                result,
                payout_per_contract,
                gross_payout,
                pnl,
                bankroll_before,
                bankroll_after,
                peak_bankroll,
                drawdown,
            ),
        )
        settlement_id = int(cursor.lastrowid)

        note = f"Settled {result}; P&L {pnl:+.2f}"

        connection.execute(
            """
            UPDATE paper_trades
            SET
                status = 'CLOSED',
                closed_at = ?,
                won = ?,
                pnl = ?,
                notes = CASE
                    WHEN notes IS NULL OR notes = ''
                    THEN ?
                    ELSE notes || ' | ' || ?
                END
            WHERE id = ?
              AND status = 'OPEN'
            """,
            (
                closed_at,
                int(won),
                pnl,
                note,
                note,
                paper_trade_id,
            ),
        )

        payload = market or {}
        connection.execute(
            """
            UPDATE markets
            SET
                status = ?,
                settlement_value = COALESCE(
                    ?,
                    settlement_value
                ),
                settled_up = ?,
                raw_json = COALESCE(?, raw_json),
                updated_at = ?
            WHERE ticker = ?
            """,
            (
                payload.get("status") or "finalized",
                _float_or_none(
                    payload.get(
                        "settlement_value_dollars"
                    )
                    or payload.get("settlement_value")
                ),
                1 if result == "YES" else 0,
                (
                    json.dumps(payload, default=str)
                    if payload
                    else None
                ),
                utc_now(),
                ticker,
            ),
        )

        return PaperSettlementSaveResult(
            created=True,
            settlement_id=settlement_id,
            paper_trade_id=paper_trade_id,
            market_ticker=ticker,
            side=side,
            market_result=result,
            won=won,
            pnl=pnl,
            bankroll_before=bankroll_before,
            bankroll_after=bankroll_after,
            peak_bankroll=peak_bankroll,
            drawdown=drawdown,
            reason="Paper trade settled",
        )


def paper_trade_summary(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    starting_bankroll: float = 1000.0,
) -> dict[str, Any]:
    if starting_bankroll <= 0:
        raise ValueError(
            "starting_bankroll must be greater than zero"
        )

    initialize_settlement_store(db_path)

    with database_connection(db_path) as connection:
        trade_row = connection.execute(
            """
            SELECT
                COUNT(*) AS total_trades,
                SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END)
                    AS open_trades,
                SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END)
                    AS closed_trades,
                SUM(
                    CASE WHEN status = 'CLOSED' AND won = 1
                    THEN 1 ELSE 0 END
                ) AS wins,
                SUM(
                    CASE WHEN status = 'CLOSED' AND won = 0
                    THEN 1 ELSE 0 END
                ) AS losses,
                COALESCE(SUM(stake), 0) AS total_stake,
                COALESCE(SUM(
                    CASE WHEN status = 'OPEN'
                    THEN stake ELSE 0 END
                ), 0) AS active_stake,
                COALESCE(SUM(
                    CASE WHEN status = 'CLOSED'
                    THEN pnl ELSE 0 END
                ), 0) AS realized_pnl,
                COALESCE(AVG(
                    CASE WHEN status = 'CLOSED'
                    THEN pnl END
                ), 0) AS average_pnl
            FROM paper_trades
            """
        ).fetchone()

        performance_row = connection.execute(
            """
            SELECT
                COALESCE(MIN(drawdown), 0)
                    AS max_drawdown,
                COALESCE(MAX(peak_bankroll), ?)
                    AS peak_bankroll
            FROM paper_trade_settlements
            """,
            (starting_bankroll,),
        ).fetchone()

        decision_row = connection.execute(
            """
            SELECT
                COUNT(*) AS total_decisions,
                SUM(CASE WHEN decision = 'OPEN' THEN 1 ELSE 0 END)
                    AS open_decisions,
                SUM(CASE WHEN decision = 'SKIP' THEN 1 ELSE 0 END)
                    AS skipped_decisions,
                SUM(CASE WHEN decision = 'BLOCKED' THEN 1 ELSE 0 END)
                    AS blocked_decisions
            FROM paper_trade_decisions
            """
        ).fetchone()

    closed = int(trade_row["closed_trades"] or 0)
    wins = int(trade_row["wins"] or 0)
    realized_pnl = float(trade_row["realized_pnl"] or 0)

    return {
        "starting_bankroll": float(starting_bankroll),
        "current_bankroll": starting_bankroll + realized_pnl,
        "peak_bankroll": max(
            starting_bankroll,
            float(
                performance_row["peak_bankroll"]
                or starting_bankroll
            ),
        ),
        "total_trades": int(trade_row["total_trades"] or 0),
        "open_trades": int(trade_row["open_trades"] or 0),
        "closed_trades": closed,
        "wins": wins,
        "losses": int(trade_row["losses"] or 0),
        "win_rate": wins / closed if closed else 0.0,
        "total_stake": float(trade_row["total_stake"] or 0),
        "active_stake": float(trade_row["active_stake"] or 0),
        "realized_pnl": realized_pnl,
        "average_pnl": float(trade_row["average_pnl"] or 0),
        "roi": realized_pnl / starting_bankroll,
        "max_drawdown": float(
            performance_row["max_drawdown"] or 0
        ),
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


def recent_paper_trades(
    *,
    limit: int = 200,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    initialize_settlement_store(db_path)

    with database_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                t.id,
                t.market_ticker,
                t.opened_at,
                t.side,
                t.entry_price,
                t.model_probability,
                t.edge,
                t.contracts,
                t.stake,
                t.status,
                t.closed_at,
                t.won,
                t.pnl,
                t.notes,
                s.market_result,
                s.payout_per_contract,
                s.gross_payout,
                s.bankroll_before,
                s.bankroll_after,
                s.peak_bankroll,
                s.drawdown
            FROM paper_trades AS t
            LEFT JOIN paper_trade_settlements AS s
              ON s.paper_trade_id = t.id
            ORDER BY t.opened_at DESC, t.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def paper_bankroll_history(
    *,
    limit: int = 1000,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    initialize_settlement_store(db_path)

    with database_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                s.settled_at,
                s.paper_trade_id,
                s.market_ticker,
                t.side,
                s.market_result,
                t.entry_price,
                t.contracts,
                t.stake,
                s.gross_payout,
                s.pnl,
                s.bankroll_before,
                s.bankroll_after,
                s.peak_bankroll,
                s.drawdown,
                t.won
            FROM paper_trade_settlements AS s
            JOIN paper_trades AS t
              ON t.id = s.paper_trade_id
            ORDER BY s.settled_at, s.id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


class PaperTradeSettlementEngine:
    """Close paper trades only after a final YES or NO result."""

    FINAL_STATUSES = {"FINALIZED", "SETTLED"}

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        rest_client: SettlementMarketClient | None = None,
        db_path: str | Path = DEFAULT_DB_PATH,
    ) -> None:
        self.settings = settings or Settings()
        self.db_path = Path(db_path)
        self.rest = (
            rest_client
            if rest_client is not None
            else KalshiREST(self.settings)
        )

        self.checked_market_count = 0
        self.settled_count = 0
        self.pending_count = 0
        self.duplicate_count = 0
        self.error_count = 0
        self.last_error: str | None = None

    @staticmethod
    def _market_result(
        market: dict[str, Any],
    ) -> str | None:
        return _normalized_result(
            market.get("result")
            or market.get("market_result")
        )

    @classmethod
    def _is_final(
        cls,
        market: dict[str, Any],
    ) -> bool:
        status = str(
            market.get("status") or ""
        ).strip().upper()

        if status in cls.FINAL_STATUSES:
            return True

        return bool(
            market.get("settlement_ts")
            or market.get("settled_time")
        )

    def _fetch_market(
        self,
        ticker: str,
    ) -> dict[str, Any]:
        try:
            return self.rest.market(ticker)
        except Exception:
            historical = getattr(
                self.rest,
                "historical_market",
                None,
            )

            if not callable(historical):
                raise

            return historical(ticker)

    def settle_open_trades(
        self,
    ) -> SettlementBatchResult:
        open_trades = open_paper_trades(
            db_path=self.db_path,
        )

        if not open_trades:
            return SettlementBatchResult(
                checked_markets=0,
                open_trades=0,
                settled=0,
                pending=0,
                duplicates=0,
                errors=0,
                outcomes=(),
            )

        grouped: dict[str, list[dict[str, Any]]] = {}

        for trade in open_trades:
            ticker = str(trade["market_ticker"])
            grouped.setdefault(ticker, []).append(trade)

        checked = 0
        settled = 0
        pending = 0
        duplicates = 0
        errors = 0
        outcomes: list[PaperSettlementSaveResult] = []

        for ticker, trades in grouped.items():
            try:
                market = self._fetch_market(ticker)
                checked += 1
                self.checked_market_count += 1

                record_market_state(
                    market,
                    fallback_ticker=ticker,
                    db_path=self.db_path,
                )

                result = self._market_result(market)

                if not self._is_final(market) or result is None:
                    count = len(trades)
                    pending += count
                    self.pending_count += count
                    continue

                settled_at = (
                    market.get("settlement_ts")
                    or market.get("settled_time")
                    or market.get("updated_time")
                )

                for trade in trades:
                    outcome = settle_paper_trade(
                        paper_trade_id=int(trade["id"]),
                        market_result=result,
                        starting_bankroll=(
                            self.settings.paper_bankroll
                        ),
                        settled_at=(
                            str(settled_at)
                            if settled_at
                            else None
                        ),
                        market=market,
                        db_path=self.db_path,
                    )
                    outcomes.append(outcome)

                    if outcome.created:
                        settled += 1
                        self.settled_count += 1
                    else:
                        duplicates += 1
                        self.duplicate_count += 1

            except Exception as exc:
                count = len(trades)
                errors += count
                self.error_count += count
                self.last_error = f"{ticker}: {exc}"

        return SettlementBatchResult(
            checked_markets=checked,
            open_trades=len(open_trades),
            settled=settled,
            pending=pending,
            duplicates=duplicates,
            errors=errors,
            outcomes=tuple(outcomes),
        )
