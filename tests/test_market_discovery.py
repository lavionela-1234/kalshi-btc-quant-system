from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from kalshi_quant.config import Settings
from kalshi_quant.market_discovery import (
    MarketDiscoveryEngine,
    recent_market_selections,
)


class FakeDiscoveryRest:
    def __init__(
        self,
        series_markets: dict[str, list[dict]],
    ) -> None:
        self.series_markets = series_markets
        self.market_calls = 0
        self.markets_calls: list[str] = []

    def markets(self, **params) -> list[dict]:
        series = str(params["series_ticker"])
        self.markets_calls.append(series)
        return [
            dict(market)
            for market in self.series_markets.get(
                series,
                [],
            )
        ]

    def market(self, ticker: str) -> dict:
        self.market_calls += 1

        for markets in self.series_markets.values():
            for market in markets:
                if market["ticker"] == ticker:
                    return dict(market)

        raise KeyError(ticker)


def make_market(
    ticker: str,
    *,
    series: str,
    target: float = 64000.0,
    seconds: float = 300.0,
    strike_type: str = "greater",
    yes_bid: str = "0.49",
    yes_ask: str = "0.50",
    no_bid: str = "0.50",
    no_ask: str = "0.51",
    volume: str = "1000",
    open_interest: str = "500",
) -> dict:
    return {
        "ticker": ticker,
        "event_ticker": f"{series}-EVENT",
        "series_ticker": series,
        "title": "BTC test market",
        "status": "active",
        "strike_type": strike_type,
        "floor_strike": target,
        "open_time": datetime.now(
            timezone.utc
        ).isoformat(),
        "close_time": (
            datetime.now(timezone.utc)
            + timedelta(seconds=seconds)
        ).isoformat(),
        "yes_bid_dollars": yes_bid,
        "yes_ask_dollars": yes_ask,
        "no_bid_dollars": no_bid,
        "no_ask_dollars": no_ask,
        "volume_fp": volume,
        "open_interest_fp": open_interest,
    }


def settings(**overrides) -> Settings:
    values = {
        "kalshi_auto_discovery": True,
        "kalshi_market_ticker": "",
        "kalshi_target_price": 0.0,
        "kalshi_primary_series": "KXBTC15M",
        "kalshi_fallback_series": "KXBTCD",
        "market_discovery_refresh_seconds": 15.0,
        "market_discovery_min_seconds": 15.0,
        "market_discovery_max_seconds": 1200.0,
        "market_discovery_max_spread": 0.08,
        "market_discovery_min_price": 0.02,
        "market_discovery_max_price": 0.98,
        "market_discovery_max_target_distance": 5000.0,
        "market_discovery_min_volume": 0.0,
        "market_discovery_min_open_interest": 0.0,
    }
    values.update(overrides)
    return Settings(**values)


def test_prefers_primary_15_minute_series(
    tmp_path: Path,
) -> None:
    rest = FakeDiscoveryRest(
        {
            "KXBTC15M": [
                make_market(
                    "PRIMARY",
                    series="KXBTC15M",
                )
            ],
            "KXBTCD": [
                make_market(
                    "FALLBACK",
                    series="KXBTCD",
                )
            ],
        }
    )
    engine = MarketDiscoveryEngine(
        settings=settings(),
        rest_client=rest,
        db_path=tmp_path / "primary.db",
    )

    result = engine.select_market(
        btc_price=63950.0,
        force=True,
    )

    assert result.candidate is not None
    assert result.candidate.ticker == "PRIMARY"
    assert rest.markets_calls == ["KXBTC15M"]


def test_falls_back_when_primary_is_ineligible(
    tmp_path: Path,
) -> None:
    rest = FakeDiscoveryRest(
        {
            "KXBTC15M": [
                make_market(
                    "RANGE",
                    series="KXBTC15M",
                    strike_type="between",
                )
            ],
            "KXBTCD": [
                make_market(
                    "FALLBACK",
                    series="KXBTCD",
                    target=64050.0,
                )
            ],
        }
    )
    engine = MarketDiscoveryEngine(
        settings=settings(),
        rest_client=rest,
        db_path=tmp_path / "fallback.db",
    )

    result = engine.select_market(
        btc_price=64000.0,
        force=True,
    )

    assert result.candidate is not None
    assert result.candidate.ticker == "FALLBACK"
    assert rest.markets_calls == [
        "KXBTC15M",
        "KXBTCD",
    ]


def test_rejects_extreme_contract_prices(
    tmp_path: Path,
) -> None:
    rest = FakeDiscoveryRest(
        {
            "KXBTC15M": [
                make_market(
                    "EXTREME",
                    series="KXBTC15M",
                    yes_bid="0.99",
                    yes_ask="1.00",
                    no_bid="0.00",
                    no_ask="0.01",
                )
            ],
            "KXBTCD": [],
        }
    )
    engine = MarketDiscoveryEngine(
        settings=settings(),
        rest_client=rest,
        db_path=tmp_path / "extreme.db",
    )

    result = engine.select_market(
        btc_price=64000.0,
        force=True,
    )

    assert result.candidate is None
    assert result.rejected_count == 1


def test_selection_history_records_rollover_only(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "history.db"
    rest = FakeDiscoveryRest(
        {
            "KXBTC15M": [
                make_market(
                    "FIRST",
                    series="KXBTC15M",
                )
            ]
        }
    )
    engine = MarketDiscoveryEngine(
        settings=settings(),
        rest_client=rest,
        db_path=db_path,
    )

    first = engine.select_market(
        btc_price=64000.0,
        force=True,
    )
    repeated = engine.select_market(
        btc_price=64010.0,
        force=True,
    )

    rest.series_markets["KXBTC15M"] = [
        make_market(
            "SECOND",
            series="KXBTC15M",
            target=64100.0,
        )
    ]
    second = engine.select_market(
        btc_price=64020.0,
        force=True,
    )

    history = recent_market_selections(
        limit=10,
        db_path=db_path,
    )

    assert first.changed is True
    assert repeated.changed is False
    assert second.changed is True
    assert len(history) == 2
    assert history[0]["market_ticker"] == "SECOND"
    assert history[0]["previous_ticker"] == "FIRST"
    assert history[0]["rollover"] == 1


def test_manual_mode_uses_configured_market(
    tmp_path: Path,
) -> None:
    rest = FakeDiscoveryRest(
        {
            "MANUAL": [
                make_market(
                    "MANUAL-TICKER",
                    series="MANUAL",
                )
            ]
        }
    )
    engine = MarketDiscoveryEngine(
        settings=settings(
            kalshi_auto_discovery=False,
            kalshi_market_ticker="MANUAL-TICKER",
            kalshi_target_price=64500.0,
        ),
        rest_client=rest,
        db_path=tmp_path / "manual.db",
    )

    result = engine.select_market(
        btc_price=64000.0,
        force=True,
    )

    assert result.candidate is not None
    assert result.candidate.ticker == "MANUAL-TICKER"
    assert result.candidate.target_price == 64500.0
    assert rest.market_calls == 1
