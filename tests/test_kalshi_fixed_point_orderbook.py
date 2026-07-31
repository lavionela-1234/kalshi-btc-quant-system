from __future__ import annotations

from typing import Any

import pytest

from kalshi_quant.config import Settings
from kalshi_quant.kalshi import Book, KalshiREST


class FixedPointRest(KalshiREST):
    def __init__(self) -> None:
        super().__init__(Settings())

    def _get(
        self,
        path: str,
        params: dict | None = None,
        auth: bool = False,
    ) -> dict[str, Any]:
        return {
            "orderbook_fp": {
                "yes_dollars": [
                    ["0.9400", "12.50"],
                    ["0.9490", "30.00"],
                ],
                "no_dollars": [
                    ["0.0400", "5.00"],
                    ["0.0490", "25.25"],
                ],
            }
        }


def test_book_preserves_legacy_integer_cent_snapshot() -> None:
    book = Book()
    book.apply_snapshot(
        {
            "yes": [[53, 100]],
            "no": [[45, 80]],
        }
    )

    assert book.yes_bid == pytest.approx(0.53)
    assert book.no_bid == pytest.approx(0.45)
    assert book.yes_ask == pytest.approx(0.55)
    assert book.no_ask == pytest.approx(0.47)


def test_rest_orderbook_parses_fixed_point_dollars() -> None:
    book = FixedPointRest().orderbook("TEST-BTC")

    assert book.yes_bid == pytest.approx(0.949)
    assert book.no_bid == pytest.approx(0.049)
    assert book.yes_ask == pytest.approx(0.951)
    assert book.no_ask == pytest.approx(0.051)
    assert book.imbalance() == pytest.approx(
        (42.5 - 30.25) / (42.5 + 30.25)
    )


def test_fixed_point_delta_updates_subcent_level() -> None:
    book = Book()
    book.apply_snapshot(
        {
            "yes_dollars": [["0.9490", "30.00"]],
            "no_dollars": [["0.0490", "25.00"]],
        }
    )

    book.apply_delta(
        {
            "side": "yes",
            "price_dollars": "0.9490",
            "delta_fp": "-10.00",
        }
    )

    assert book.yes_bid == pytest.approx(0.949)
    assert book.yes[9490] == pytest.approx(20.0)
