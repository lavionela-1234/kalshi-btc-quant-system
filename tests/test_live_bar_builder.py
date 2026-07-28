from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kalshi_quant.bars import bar_count, latest_bar
from kalshi_quant.live_bar_builder import LiveBarBuilder


def make_trade(
    trade_id: str,
    timestamp: str,
    price: float,
    size: float,
    side: str,
) -> dict[str, Any]:
    return {
        "trade_id": trade_id,
        "product_id": "BTC-USD",
        "timestamp": timestamp,
        "price": price,
        "size": size,
        "side": side,
    }


def test_live_builder_closes_and_saves_bars(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "live-bars.db"
    builder = LiveBarBuilder(
        intervals=(1, 5),
        db_path=db_path,
        checkpoint_every=0,
    )

    builder.process_trade(
        make_trade(
            "1",
            "2026-07-27T12:00:00.100000Z",
            100.0,
            2.0,
            "BUY",
        )
    )
    builder.process_trade(
        make_trade(
            "2",
            "2026-07-27T12:00:00.700000Z",
            103.0,
            1.0,
            "SELL",
        )
    )

    closed = builder.process_trade(
        make_trade(
            "3",
            "2026-07-27T12:00:01.100000Z",
            101.0,
            3.0,
            "BUY",
        )
    )

    assert len(closed) == 1
    assert closed[0].interval_seconds == 1
    assert closed[0].open == pytest.approx(100.0)
    assert closed[0].high == pytest.approx(103.0)
    assert closed[0].low == pytest.approx(100.0)
    assert closed[0].close == pytest.approx(103.0)
    assert closed[0].volume == pytest.approx(3.0)
    assert closed[0].trade_count == 2
    assert closed[0].buy_volume == pytest.approx(2.0)
    assert closed[0].sell_volume == pytest.approx(1.0)
    assert closed[0].volume_imbalance == pytest.approx(1.0 / 3.0)

    assert bar_count(1, db_path=db_path) == 1
    assert bar_count(5, db_path=db_path) == 0

    flushed = builder.flush()

    assert len(flushed) == 2
    assert bar_count(1, db_path=db_path) == 2
    assert bar_count(5, db_path=db_path) == 1


def test_checkpoint_can_resume_same_partial_bar(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "resume-bars.db"

    first_builder = LiveBarBuilder(
        intervals=(60,),
        db_path=db_path,
        checkpoint_every=0,
    )
    first_builder.process_trade(
        make_trade(
            "1",
            "2026-07-27T12:00:10Z",
            100.0,
            1.5,
            "BUY",
        )
    )
    assert first_builder.checkpoint() == 1

    second_builder = LiveBarBuilder(
        intervals=(60,),
        db_path=db_path,
        checkpoint_every=0,
    )
    second_builder.process_trade(
        make_trade(
            "2",
            "2026-07-27T12:00:20Z",
            102.0,
            0.5,
            "SELL",
        )
    )
    second_builder.flush()

    stored = latest_bar(
        interval_seconds=60,
        db_path=db_path,
    )

    assert stored is not None
    assert stored["open"] == pytest.approx(100.0)
    assert stored["high"] == pytest.approx(102.0)
    assert stored["low"] == pytest.approx(100.0)
    assert stored["close"] == pytest.approx(102.0)
    assert stored["volume"] == pytest.approx(2.0)
    assert stored["trade_count"] == 2
    assert stored["buy_volume"] == pytest.approx(1.5)
    assert stored["sell_volume"] == pytest.approx(0.5)
    assert stored["volume_imbalance"] == pytest.approx(0.5)


def test_invalid_intervals_are_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        LiveBarBuilder(
            intervals=(0, 5),
            db_path=tmp_path / "invalid.db",
        )
