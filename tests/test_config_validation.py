from __future__ import annotations

import pytest

from kalshi_quant.config import Settings


def test_default_settings_are_valid() -> None:
    Settings()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("paper_bankroll", 0),
        ("market_discovery_refresh_seconds", 0),
        ("paper_min_confidence", 1.01),
        ("min_edge", -0.01),
        ("cost_buffer", 1.01),
        ("kelly_fraction", -0.01),
        ("max_position_fraction", 1.01),
        ("daily_loss_limit_fraction", 0),
    ],
)
def test_invalid_numeric_settings_fail_fast(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        Settings(**{field: value})


def test_invalid_environment_fails_fast() -> None:
    with pytest.raises(ValueError, match="KALSHI_ENV"):
        Settings(kalshi_env="live")


def test_inverted_time_windows_fail_fast() -> None:
    with pytest.raises(ValueError, match="MARKET_DISCOVERY"):
        Settings(
            market_discovery_min_seconds=300,
            market_discovery_max_seconds=30,
        )

    with pytest.raises(ValueError, match="PAPER"):
        Settings(paper_min_seconds=300, paper_max_seconds=30)


def test_inverted_price_window_fails_fast() -> None:
    with pytest.raises(ValueError, match="MARKET_DISCOVERY.*PRICE"):
        Settings(
            market_discovery_min_price=0.8,
            market_discovery_max_price=0.2,
        )
