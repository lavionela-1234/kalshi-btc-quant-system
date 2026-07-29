from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from kalshi_quant.automatic_signal_pipeline import (
    AutomaticSignalPipeline,
)
from kalshi_quant.bars import MarketBar, save_market_bar
from kalshi_quant.signal_store import signal_history_count


def make_bar(
    *,
    start: datetime,
    interval_seconds: int,
    index: int,
    bullish: bool = True,
) -> MarketBar:
    direction = 1.0 if bullish else -1.0
    open_price = 100.0 + direction * index * 0.20
    close_price = open_price + direction * 0.15
    end = start + timedelta(seconds=interval_seconds)

    return MarketBar(
        product_id="BTC-USD",
        interval_seconds=interval_seconds,
        start_time=start.isoformat().replace("+00:00", "Z"),
        end_time=end.isoformat().replace("+00:00", "Z"),
        open=open_price,
        high=max(open_price, close_price) + 0.05,
        low=min(open_price, close_price) - 0.05,
        close=close_price,
        volume=10.0,
        trade_count=20,
        buy_volume=7.0 if bullish else 3.0,
        sell_volume=3.0 if bullish else 7.0,
        volume_imbalance=0.4 if bullish else -0.4,
    )


def populate_bars(
    db_path: Path,
    *,
    interval_seconds: int,
    count: int,
    start: datetime,
) -> list[MarketBar]:
    bars: list[MarketBar] = []

    for index in range(count):
        bar = make_bar(
            start=(
                start
                + timedelta(seconds=index * interval_seconds)
            ),
            interval_seconds=interval_seconds,
            index=index,
        )
        save_market_bar(bar, db_path=db_path)
        bars.append(bar)

    return bars


def test_pipeline_creates_one_signal_for_completed_primary_bar(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "automatic-signals.sqlite3"
    start = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)

    primary = populate_bars(
        db_path,
        interval_seconds=5,
        count=30,
        start=start,
    )
    populate_bars(
        db_path,
        interval_seconds=60,
        count=25,
        start=start - timedelta(minutes=24),
    )

    pipeline = AutomaticSignalPipeline(
        db_path=db_path,
        min_bars=20,
    )

    signals = pipeline.process_closed_bars([primary[-1]])

    assert len(signals) == 1
    assert signal_history_count(
        interval_seconds=5,
        db_path=db_path,
    ) == 1
    assert signals[0].timeframe_confirmation != "UNAVAILABLE"


def test_pipeline_skips_duplicate_completed_bar(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "duplicates.sqlite3"
    start = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    primary = populate_bars(
        db_path,
        interval_seconds=5,
        count=25,
        start=start,
    )

    pipeline = AutomaticSignalPipeline(
        db_path=db_path,
        min_bars=20,
    )

    assert len(pipeline.process_closed_bars([primary[-1]])) == 1
    assert pipeline.process_closed_bars([primary[-1]]) == []
    assert pipeline.duplicate_skip_count == 1
    assert signal_history_count(
        interval_seconds=5,
        db_path=db_path,
    ) == 1


def test_pipeline_waits_for_enough_primary_bars(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "insufficient.sqlite3"
    start = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    primary = populate_bars(
        db_path,
        interval_seconds=5,
        count=10,
        start=start,
    )

    pipeline = AutomaticSignalPipeline(
        db_path=db_path,
        min_bars=20,
    )

    assert pipeline.process_closed_bars([primary[-1]]) == []
    assert pipeline.insufficient_data_skip_count == 1
    assert signal_history_count(
        interval_seconds=5,
        db_path=db_path,
    ) == 0


def test_pipeline_ignores_non_primary_bars(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "ignored.sqlite3"
    start = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    minute_bar = make_bar(
        start=start,
        interval_seconds=60,
        index=1,
    )
    save_market_bar(minute_bar, db_path=db_path)

    pipeline = AutomaticSignalPipeline(db_path=db_path)

    assert pipeline.process_closed_bars([minute_bar]) == []
    assert pipeline.ignored_bar_count == 1
