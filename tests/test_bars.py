from __future__ import annotations

import pytest

from kalshi_quant.bars import (
    aggregate_trades,
    calculate_volume_imbalance,
    floor_timestamp,
    parse_timestamp,
)


def sample_trades() -> list[dict]:
    return [
        {
            "trade_id": "1",
            "product_id": "BTC-USD",
            "timestamp": "2026-07-27T22:31:01Z",
            "price": 100.0,
            "size": 2.0,
            "side": "BUY",
        },
        {
            "trade_id": "2",
            "product_id": "BTC-USD",
            "timestamp": "2026-07-27T22:31:20Z",
            "price": 105.0,
            "size": 1.0,
            "side": "SELL",
        },
        {
            "trade_id": "3",
            "product_id": "BTC-USD",
            "timestamp": "2026-07-27T22:31:50Z",
            "price": 98.0,
            "size": 3.0,
            "side": "BUY",
        },
        {
            "trade_id": "4",
            "product_id": "BTC-USD",
            "timestamp": "2026-07-27T22:32:10Z",
            "price": 110.0,
            "size": 4.0,
            "side": "SELL",
        },
    ]


def test_aggregate_trades_creates_ohlcv_bar() -> None:
    bars = aggregate_trades(
        sample_trades(),
        interval_seconds=60,
    )

    assert len(bars) == 2

    first = bars[0]

    assert first.start_time == "2026-07-27T22:31:00Z"
    assert first.end_time == "2026-07-27T22:32:00Z"
    assert first.open == 100.0
    assert first.high == 105.0
    assert first.low == 98.0
    assert first.close == 98.0
    assert first.volume == 6.0
    assert first.trade_count == 3
    assert first.buy_volume == 5.0
    assert first.sell_volume == 1.0
    assert first.volume_imbalance == pytest.approx(4.0 / 6.0)


def test_volume_imbalance() -> None:
    assert calculate_volume_imbalance(5.0, 5.0) == 0.0
    assert calculate_volume_imbalance(10.0, 0.0) == 1.0
    assert calculate_volume_imbalance(0.0, 10.0) == -1.0
    assert calculate_volume_imbalance(0.0, 0.0) == 0.0


def test_floor_timestamp_to_minute() -> None:
    timestamp = parse_timestamp(
        "2026-07-27T22:31:45.123456Z"
    )

    floored = floor_timestamp(
        timestamp,
        interval_seconds=60,
    )

    assert (
        floored.isoformat()
        == "2026-07-27T22:31:00+00:00"
    )


def test_invalid_interval_is_rejected() -> None:
    with pytest.raises(ValueError):
        aggregate_trades(
            sample_trades(),
            interval_seconds=0,
        )