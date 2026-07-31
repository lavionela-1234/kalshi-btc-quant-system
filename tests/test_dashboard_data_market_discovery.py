from __future__ import annotations

from pathlib import Path

from kalshi_quant.dashboard_data import (
    current_market_selection,
    recent_market_selections,
)
from kalshi_quant.market_discovery import (
    MarketCandidate,
    MarketSelectionResult,
    save_market_selection,
)


def candidate(
    ticker: str,
    *,
    target: float,
) -> MarketCandidate:
    return MarketCandidate(
        ticker=ticker,
        event_ticker=f"{ticker}-EVENT",
        series_ticker="KXBTC15M",
        title="BTC price up in next 15 mins?",
        target_price=target,
        btc_price=64000.0,
        close_time="2026-07-31T00:15:00+00:00",
        seconds_remaining=600.0,
        yes_bid=0.49,
        yes_ask=0.50,
        no_bid=0.50,
        no_ask=0.51,
        spread=0.01,
        volume=1000.0,
        open_interest=500.0,
        distance_from_btc=abs(target - 64000.0),
        raw_market={
            "ticker": ticker,
            "status": "active",
            "strike_type": "greater_or_equal",
        },
    )


def test_dashboard_market_selection_loaders(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "dashboard-discovery.db"

    first = MarketSelectionResult(
        candidate=candidate("BTC-FIRST", target=63950.0),
        reason="Selected primary BTC series",
        scanned_count=1,
        rejected_count=0,
        changed=True,
        previous_ticker=None,
    )
    second = MarketSelectionResult(
        candidate=candidate("BTC-SECOND", target=64050.0),
        reason="Rolled to next eligible BTC market",
        scanned_count=1,
        rejected_count=0,
        changed=True,
        previous_ticker="BTC-FIRST",
    )

    assert save_market_selection(
        first,
        db_path=db_path,
    ) is not None
    assert save_market_selection(
        second,
        db_path=db_path,
    ) is not None

    selected = current_market_selection(
        db_path=db_path,
    )
    history = recent_market_selections(
        limit=10,
        db_path=db_path,
    )

    assert selected is not None
    assert selected["market_ticker"] == "BTC-SECOND"
    assert selected["previous_ticker"] == "BTC-FIRST"
    assert selected["rollover"] == 1

    assert len(history) == 2
    assert history.iloc[0]["market_ticker"] == "BTC-SECOND"
    assert history.iloc[0]["rollover"] == 1
    assert str(history["selected_at"].dtype).startswith(
        "datetime64"
    )
