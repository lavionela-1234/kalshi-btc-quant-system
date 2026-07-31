from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any, Protocol

from .config import Settings
from .db import (
    DEFAULT_DB_PATH,
    database_connection,
    initialize_database,
    utc_now,
)


MARKET_SELECTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_selection_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    selected_at TEXT NOT NULL,
    market_ticker TEXT NOT NULL,
    event_ticker TEXT,
    series_ticker TEXT NOT NULL,
    target_price REAL NOT NULL,
    btc_price REAL NOT NULL,
    seconds_remaining REAL NOT NULL,
    yes_bid REAL,
    yes_ask REAL,
    no_bid REAL,
    no_ask REAL,
    spread REAL,
    volume REAL NOT NULL DEFAULT 0,
    open_interest REAL NOT NULL DEFAULT 0,
    selection_reason TEXT NOT NULL,
    previous_ticker TEXT,
    rollover INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT,
    FOREIGN KEY (market_ticker) REFERENCES markets(ticker)
);

CREATE INDEX IF NOT EXISTS idx_market_selection_history_time
ON market_selection_history(selected_at, id);

CREATE INDEX IF NOT EXISTS idx_market_selection_history_ticker
ON market_selection_history(market_ticker, selected_at);
"""


class MarketDiscoveryClient(Protocol):
    def markets(self, **params: Any) -> list[dict[str, Any]]:
        ...

    def market(self, ticker: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class MarketCandidate:
    ticker: str
    event_ticker: str | None
    series_ticker: str
    title: str
    target_price: float
    btc_price: float
    close_time: str
    seconds_remaining: float
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    spread: float | None
    volume: float
    open_interest: float
    distance_from_btc: float
    raw_market: dict[str, Any]


@dataclass(frozen=True)
class MarketSelectionResult:
    candidate: MarketCandidate | None
    reason: str
    scanned_count: int
    rejected_count: int
    changed: bool
    previous_ticker: str | None


def initialize_market_selection_store(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Path:
    path = initialize_database(db_path)

    with database_connection(path) as connection:
        connection.executescript(MARKET_SELECTION_SCHEMA)

    return path


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quote(
    market: dict[str, Any],
    dollar_key: str,
    legacy_key: str,
) -> float | None:
    value = _float_or_none(market.get(dollar_key))

    if value is None:
        value = _float_or_none(market.get(legacy_key))

        if value is not None and value > 1:
            value /= 100.0

    if value is None:
        return None

    if not 0 <= value <= 1:
        return None

    return value


def _parse_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None

    try:
        timestamp = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except ValueError:
        return None

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(timezone.utc)


def _target_price(
    market: dict[str, Any],
) -> float | None:
    for key in (
        "target_price",
        "floor_strike",
        "strike",
        "cap_strike",
    ):
        parsed = _float_or_none(market.get(key))

        if parsed is not None and parsed > 0:
            return parsed

    return None


def _close_time(
    market: dict[str, Any],
) -> tuple[str, datetime] | None:
    raw = (
        market.get("close_time")
        or market.get("latest_expiration_time")
        or market.get("expected_expiration_time")
    )
    parsed = _parse_time(raw)

    if parsed is None:
        return None

    return str(raw), parsed


def _market_title(
    market: dict[str, Any],
    ticker: str,
) -> str:
    return str(
        market.get("title")
        or market.get("subtitle")
        or market.get("yes_sub_title")
        or ticker
    )


def _market_record_values(
    candidate: MarketCandidate,
) -> tuple[Any, ...]:
    now = utc_now()
    market = candidate.raw_market

    return (
        candidate.ticker,
        candidate.title,
        candidate.target_price,
        market.get("open_time"),
        candidate.close_time,
        market.get("status"),
        json.dumps(market, default=str),
        now,
        now,
    )


def save_market_selection(
    result: MarketSelectionResult,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int | None:
    candidate = result.candidate

    if candidate is None or not result.changed:
        return None

    initialize_market_selection_store(db_path)
    selected_at = utc_now()

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
                raw_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker)
            DO UPDATE SET
                title = excluded.title,
                target_price = excluded.target_price,
                open_time = excluded.open_time,
                close_time = excluded.close_time,
                status = excluded.status,
                raw_json = excluded.raw_json,
                updated_at = excluded.updated_at
            """,
            _market_record_values(candidate),
        )

        cursor = connection.execute(
            """
            INSERT INTO market_selection_history (
                selected_at,
                market_ticker,
                event_ticker,
                series_ticker,
                target_price,
                btc_price,
                seconds_remaining,
                yes_bid,
                yes_ask,
                no_bid,
                no_ask,
                spread,
                volume,
                open_interest,
                selection_reason,
                previous_ticker,
                rollover,
                raw_json
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                selected_at,
                candidate.ticker,
                candidate.event_ticker,
                candidate.series_ticker,
                candidate.target_price,
                candidate.btc_price,
                candidate.seconds_remaining,
                candidate.yes_bid,
                candidate.yes_ask,
                candidate.no_bid,
                candidate.no_ask,
                candidate.spread,
                candidate.volume,
                candidate.open_interest,
                result.reason,
                result.previous_ticker,
                int(result.previous_ticker is not None),
                json.dumps(
                    candidate.raw_market,
                    default=str,
                ),
            ),
        )

        return int(cursor.lastrowid)


def recent_market_selections(
    *,
    limit: int = 200,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    initialize_market_selection_store(db_path)

    with database_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                selected_at,
                market_ticker,
                event_ticker,
                series_ticker,
                target_price,
                btc_price,
                seconds_remaining,
                yes_bid,
                yes_ask,
                no_bid,
                no_ask,
                spread,
                volume,
                open_interest,
                selection_reason,
                previous_ticker,
                rollover
            FROM market_selection_history
            ORDER BY selected_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def current_market_selection(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    rows = recent_market_selections(
        limit=1,
        db_path=db_path,
    )
    return rows[0] if rows else None


class MarketDiscoveryEngine:
    """Select and roll among compatible Kalshi BTC markets."""

    ELIGIBLE_STATUSES = {"ACTIVE", "OPEN"}
    ELIGIBLE_STRIKES = {"GREATER", "GREATER_OR_EQUAL"}

    def __init__(
        self,
        *,
        settings: Settings,
        rest_client: MarketDiscoveryClient,
        db_path: str | Path = DEFAULT_DB_PATH,
    ) -> None:
        self.settings = settings
        self.rest = rest_client
        self.db_path = Path(db_path)
        self.current: MarketCandidate | None = None
        self.last_result: MarketSelectionResult | None = None
        self.last_error: str | None = None
        self._last_refresh_monotonic = 0.0

        self.selection_count = 0
        self.rollover_count = 0
        self.refresh_count = 0
        self.rejection_count = 0

    @property
    def enabled(self) -> bool:
        return (
            self.settings.kalshi_auto_discovery
            or bool(
                self.settings.kalshi_market_ticker.strip()
            )
        )

    def _remaining_seconds(
        self,
        candidate: MarketCandidate,
    ) -> float:
        parsed = _parse_time(candidate.close_time)

        if parsed is None:
            return 0.0

        return max(
            (
                parsed
                - datetime.now(timezone.utc)
            ).total_seconds(),
            0.0,
        )

    def _candidate_from_market(
        self,
        market: dict[str, Any],
        *,
        btc_price: float,
        series_ticker: str,
        require_eligibility: bool,
    ) -> tuple[MarketCandidate | None, str | None]:
        ticker = str(market.get("ticker") or "").strip()

        if not ticker:
            return None, "missing ticker"

        status = str(
            market.get("status") or ""
        ).strip().upper()

        strike_type = str(
            market.get("strike_type") or ""
        ).strip().upper()

        target = _target_price(market)
        close = _close_time(market)

        if target is None:
            return None, "missing target price"

        if close is None:
            return None, "missing close time"

        close_raw, close_timestamp = close
        seconds_remaining = max(
            (
                close_timestamp
                - datetime.now(timezone.utc)
            ).total_seconds(),
            0.0,
        )

        yes_bid = _quote(
            market,
            "yes_bid_dollars",
            "yes_bid",
        )
        yes_ask = _quote(
            market,
            "yes_ask_dollars",
            "yes_ask",
        )
        no_bid = _quote(
            market,
            "no_bid_dollars",
            "no_bid",
        )
        no_ask = _quote(
            market,
            "no_ask_dollars",
            "no_ask",
        )

        spread = (
            max(0.0, yes_ask + no_ask - 1.0)
            if yes_ask is not None
            and no_ask is not None
            else None
        )

        volume = (
            _float_or_none(market.get("volume_fp"))
            or _float_or_none(market.get("volume"))
            or 0.0
        )
        open_interest = (
            _float_or_none(
                market.get("open_interest_fp")
            )
            or _float_or_none(
                market.get("open_interest")
            )
            or 0.0
        )
        distance = abs(target - btc_price)

        if require_eligibility:
            if status not in self.ELIGIBLE_STATUSES:
                return None, f"ineligible status {status or '-'}"

            if strike_type not in self.ELIGIBLE_STRIKES:
                return None, (
                    f"incompatible strike type "
                    f"{strike_type or '-'}"
                )

            if (
                seconds_remaining
                < self.settings.market_discovery_min_seconds
            ):
                return None, "too little time remaining"

            if (
                seconds_remaining
                > self.settings.market_discovery_max_seconds
            ):
                return None, "too much time remaining"

            if (
                yes_bid is None
                or yes_ask is None
                or no_bid is None
                or no_ask is None
                or spread is None
            ):
                return None, "missing two-sided quote"

            if (
                spread
                > self.settings.market_discovery_max_spread
            ):
                return None, "spread exceeds discovery limit"

            min_price = (
                self.settings.market_discovery_min_price
            )
            max_price = (
                self.settings.market_discovery_max_price
            )

            if not (
                min_price < yes_ask < max_price
                and min_price < no_ask < max_price
            ):
                return None, "contract prices are too extreme"

            if (
                distance
                > self.settings
                .market_discovery_max_target_distance
            ):
                return None, "target is too far from BTC"

            if (
                volume
                < self.settings.market_discovery_min_volume
            ):
                return None, "volume is below discovery minimum"

            if (
                open_interest
                < self.settings
                .market_discovery_min_open_interest
            ):
                return None, (
                    "open interest is below discovery minimum"
                )

        candidate = MarketCandidate(
            ticker=ticker,
            event_ticker=(
                str(market.get("event_ticker"))
                if market.get("event_ticker")
                else None
            ),
            series_ticker=(
                str(
                    market.get("series_ticker")
                    or series_ticker
                )
            ),
            title=_market_title(market, ticker),
            target_price=target,
            btc_price=float(btc_price),
            close_time=close_raw,
            seconds_remaining=seconds_remaining,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            spread=spread,
            volume=float(volume),
            open_interest=float(open_interest),
            distance_from_btc=distance,
            raw_market=dict(market),
        )

        return candidate, None

    @staticmethod
    def _rank(candidate: MarketCandidate) -> tuple:
        liquidity = (
            candidate.volume
            + candidate.open_interest
        )

        return (
            candidate.spread
            if candidate.spread is not None
            else math.inf,
            candidate.distance_from_btc,
            -math.log1p(max(liquidity, 0.0)),
            candidate.seconds_remaining,
            candidate.ticker,
        )

    def _manual_selection(
        self,
        *,
        btc_price: float,
    ) -> MarketSelectionResult:
        ticker = (
            self.settings.kalshi_market_ticker.strip()
        )

        if not ticker:
            return MarketSelectionResult(
                candidate=None,
                reason=(
                    "KALSHI_MARKET_TICKER is not configured"
                ),
                scanned_count=0,
                rejected_count=0,
                changed=False,
                previous_ticker=(
                    self.current.ticker
                    if self.current is not None
                    else None
                ),
            )

        market = self.rest.market(ticker)

        if self.settings.kalshi_target_price > 0:
            market = dict(market)
            market["target_price"] = (
                self.settings.kalshi_target_price
            )

        candidate, rejection = self._candidate_from_market(
            market,
            btc_price=btc_price,
            series_ticker=(
                str(market.get("series_ticker") or "MANUAL")
            ),
            require_eligibility=False,
        )

        if candidate is None:
            return MarketSelectionResult(
                candidate=None,
                reason=(
                    "Configured market could not be loaded: "
                    f"{rejection}"
                ),
                scanned_count=1,
                rejected_count=1,
                changed=False,
                previous_ticker=(
                    self.current.ticker
                    if self.current is not None
                    else None
                ),
            )

        previous = (
            self.current.ticker
            if self.current is not None
            else None
        )
        changed = previous != candidate.ticker

        return MarketSelectionResult(
            candidate=candidate,
            reason="Using configured manual Kalshi market",
            scanned_count=1,
            rejected_count=0,
            changed=changed,
            previous_ticker=previous,
        )

    def _reuse_current(
        self,
        *,
        btc_price: float,
    ) -> MarketSelectionResult | None:
        if self.current is None:
            return None

        elapsed = (
            monotonic()
            - self._last_refresh_monotonic
        )

        if (
            elapsed
            >= self.settings
            .market_discovery_refresh_seconds
        ):
            return None

        remaining = self._remaining_seconds(self.current)

        if (
            remaining
            < self.settings.market_discovery_min_seconds
        ):
            return None

        refreshed = replace(
            self.current,
            btc_price=float(btc_price),
            seconds_remaining=remaining,
            distance_from_btc=abs(
                self.current.target_price - btc_price
            ),
        )
        self.current = refreshed

        return MarketSelectionResult(
            candidate=refreshed,
            reason="Reused current market before refresh interval",
            scanned_count=0,
            rejected_count=0,
            changed=False,
            previous_ticker=refreshed.ticker,
        )

    def select_market(
        self,
        *,
        btc_price: float,
        force: bool = False,
    ) -> MarketSelectionResult:
        if btc_price <= 0:
            raise ValueError(
                "btc_price must be greater than zero"
            )

        if not force:
            reused = self._reuse_current(
                btc_price=btc_price,
            )

            if reused is not None:
                self.last_result = reused
                return reused

        self.refresh_count += 1
        self._last_refresh_monotonic = monotonic()

        try:
            if not self.settings.kalshi_auto_discovery:
                result = self._manual_selection(
                    btc_price=btc_price,
                )
            else:
                result = self._discover(
                    btc_price=btc_price,
                )
        except Exception as exc:
            self.last_error = str(exc)
            result = MarketSelectionResult(
                candidate=None,
                reason=f"Market discovery failed: {exc}",
                scanned_count=0,
                rejected_count=0,
                changed=False,
                previous_ticker=(
                    self.current.ticker
                    if self.current is not None
                    else None
                ),
            )

        if result.candidate is not None:
            if result.changed:
                self.selection_count += 1

                if result.previous_ticker is not None:
                    self.rollover_count += 1

                save_market_selection(
                    result,
                    db_path=self.db_path,
                )

            self.current = result.candidate

        elif self.settings.kalshi_auto_discovery:
            self.current = None

        self.rejection_count += result.rejected_count
        self.last_result = result

        return result

    def _discover(
        self,
        *,
        btc_price: float,
    ) -> MarketSelectionResult:
        series_order = tuple(
            dict.fromkeys(
                series.strip()
                for series in (
                    self.settings.kalshi_primary_series,
                    self.settings.kalshi_fallback_series,
                )
                if series.strip()
            )
        )

        scanned = 0
        rejected = 0
        chosen: MarketCandidate | None = None
        chosen_series: str | None = None

        for series_ticker in series_order:
            markets = self.rest.markets(
                series_ticker=series_ticker,
                status="open",
                limit=1000,
                mve_filter="exclude",
            )
            candidates: list[MarketCandidate] = []

            for market in markets:
                scanned += 1
                candidate, rejection = (
                    self._candidate_from_market(
                        market,
                        btc_price=btc_price,
                        series_ticker=series_ticker,
                        require_eligibility=True,
                    )
                )

                if candidate is None:
                    rejected += 1
                    continue

                candidates.append(candidate)

            if candidates:
                chosen = min(
                    candidates,
                    key=self._rank,
                )
                chosen_series = series_ticker
                break

        previous = (
            self.current.ticker
            if self.current is not None
            else None
        )

        if chosen is None:
            return MarketSelectionResult(
                candidate=None,
                reason=(
                    "No eligible Kalshi BTC market was found "
                    f"after scanning {scanned} market(s)"
                ),
                scanned_count=scanned,
                rejected_count=rejected,
                changed=False,
                previous_ticker=previous,
            )

        changed = previous != chosen.ticker
        reason = (
            f"Selected {chosen_series} market with "
            f"{chosen.seconds_remaining:.0f}s remaining, "
            f"${chosen.distance_from_btc:,.2f} target distance"
        )

        return MarketSelectionResult(
            candidate=chosen,
            reason=reason,
            scanned_count=scanned,
            rejected_count=rejected,
            changed=changed,
            previous_ticker=previous,
        )
