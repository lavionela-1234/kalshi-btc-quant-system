from __future__ import annotations

from pathlib import Path

from kalshi_quant.config import Settings
from kalshi_quant.paper_trade_lifecycle import (
    PaperTradeSettlementEngine,
    paper_trade_summary,
    recent_paper_trades,
)
from kalshi_quant.paper_trade_store import (
    PaperDecisionRecord,
    save_paper_decision,
)


class FakeRest:
    def __init__(self, markets: dict[str, dict]) -> None:
        self.markets = markets
        self.calls: list[str] = []

    def market(self, ticker: str) -> dict:
        self.calls.append(ticker)
        return self.markets[ticker]


def create_trade(
    db_path: Path,
    *,
    ticker: str,
    timestamp: str,
) -> int:
    saved = save_paper_decision(
        PaperDecisionRecord(
            market_ticker=ticker,
            signal_timestamp=timestamp,
            technical_direction="BULLISH",
            technical_action="LONG_BIAS",
            technical_score=45.0,
            technical_probability_up=0.80,
            technical_confidence=0.70,
            btc_price=64000.0,
            target_price=63900.0,
            seconds_remaining=120.0,
            yes_bid=0.53,
            yes_ask=0.55,
            no_bid=0.45,
            no_ask=0.47,
            spread=0.02,
            decision="OPEN",
            side="YES",
            edge=0.24,
            contracts=20,
            stake=11.0,
            reason="Simulated paper trade opened",
        ),
        market={
            "ticker": ticker,
            "title": ticker,
            "status": "active",
            "close_time": "2026-07-30T12:02:00Z",
        },
        db_path=db_path,
    )
    assert saved.paper_trade_id is not None
    return saved.paper_trade_id


def test_engine_settles_only_finalized_market(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "engine.db"
    create_trade(
        db_path,
        ticker="FINAL",
        timestamp="2026-07-30T12:00:00+00:00",
    )
    create_trade(
        db_path,
        ticker="PENDING",
        timestamp="2026-07-30T12:00:05+00:00",
    )

    rest = FakeRest(
        {
            "FINAL": {
                "ticker": "FINAL",
                "status": "finalized",
                "result": "yes",
                "settlement_ts": "2026-07-30T12:05:00Z",
            },
            "PENDING": {
                "ticker": "PENDING",
                "status": "closed",
                "result": "",
            },
        }
    )
    engine = PaperTradeSettlementEngine(
        settings=Settings(paper_bankroll=1000.0),
        rest_client=rest,
        db_path=db_path,
    )

    batch = engine.settle_open_trades()

    assert batch.checked_markets == 2
    assert batch.open_trades == 2
    assert batch.settled == 1
    assert batch.pending == 1
    assert batch.errors == 0

    statuses = {
        row["market_ticker"]: row["status"]
        for row in recent_paper_trades(db_path=db_path)
    }
    assert statuses["FINAL"] == "CLOSED"
    assert statuses["PENDING"] == "OPEN"


def test_engine_fetches_one_market_for_multiple_trades(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "group.db"
    create_trade(
        db_path,
        ticker="SAME",
        timestamp="2026-07-30T12:00:00+00:00",
    )
    create_trade(
        db_path,
        ticker="SAME",
        timestamp="2026-07-30T12:00:05+00:00",
    )

    rest = FakeRest(
        {
            "SAME": {
                "ticker": "SAME",
                "status": "finalized",
                "result": "no",
                "settlement_ts": "2026-07-30T12:05:00Z",
            }
        }
    )
    engine = PaperTradeSettlementEngine(
        settings=Settings(paper_bankroll=1000.0),
        rest_client=rest,
        db_path=db_path,
    )

    batch = engine.settle_open_trades()

    assert batch.checked_markets == 1
    assert batch.settled == 2
    assert rest.calls == ["SAME"]

    summary = paper_trade_summary(
        db_path,
        starting_bankroll=1000.0,
    )
    assert summary["closed_trades"] == 2
    assert summary["losses"] == 2

    second = engine.settle_open_trades()
    assert second.open_trades == 0
    assert second.settled == 0
