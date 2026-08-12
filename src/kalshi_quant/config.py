from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    kalshi_env: str = os.getenv("KALSHI_ENV", "demo")
    kalshi_api_key_id: str = os.getenv("KALSHI_API_KEY_ID", "")
    kalshi_private_key_path: str = os.getenv(
        "KALSHI_PRIVATE_KEY_PATH",
        "",
    )
    kalshi_market_ticker: str = os.getenv(
        "KALSHI_MARKET_TICKER",
        "",
    )
    kalshi_target_price: float = float(
        os.getenv("KALSHI_TARGET_PRICE", "0")
    )

    kalshi_auto_discovery: bool = (
        os.getenv(
            "KALSHI_AUTO_DISCOVERY",
            "true",
        ).lower()
        == "true"
    )
    kalshi_primary_series: str = os.getenv(
        "KALSHI_PRIMARY_SERIES",
        "KXBTC15M",
    )
    kalshi_fallback_series: str = os.getenv(
        "KALSHI_FALLBACK_SERIES",
        "KXBTCD",
    )
    market_discovery_refresh_seconds: float = float(
        os.getenv(
            "MARKET_DISCOVERY_REFRESH_SECONDS",
            "15",
        )
    )
    market_discovery_min_seconds: float = float(
        os.getenv(
            "MARKET_DISCOVERY_MIN_SECONDS",
            "15",
        )
    )
    market_discovery_max_seconds: float = float(
        os.getenv(
            "MARKET_DISCOVERY_MAX_SECONDS",
            "1200",
        )
    )
    market_discovery_max_spread: float = float(
        os.getenv(
            "MARKET_DISCOVERY_MAX_SPREAD",
            "0.08",
        )
    )
    market_discovery_min_price: float = float(
        os.getenv(
            "MARKET_DISCOVERY_MIN_PRICE",
            "0.02",
        )
    )
    market_discovery_max_price: float = float(
        os.getenv(
            "MARKET_DISCOVERY_MAX_PRICE",
            "0.98",
        )
    )
    market_discovery_max_target_distance: float = float(
        os.getenv(
            "MARKET_DISCOVERY_MAX_TARGET_DISTANCE",
            "5000",
        )
    )
    market_discovery_min_volume: float = float(
        os.getenv(
            "MARKET_DISCOVERY_MIN_VOLUME",
            "0",
        )
    )
    market_discovery_min_open_interest: float = float(
        os.getenv(
            "MARKET_DISCOVERY_MIN_OPEN_INTEREST",
            "0",
        )
    )

    coinbase_product_id: str = os.getenv(
        "COINBASE_PRODUCT_ID",
        "BTC-USD",
    )

    paper_mode: bool = (
        os.getenv("PAPER_MODE", "true").lower() == "true"
    )
    paper_bankroll: float = float(
        os.getenv("PAPER_BANKROLL", "1000")
    )
    paper_max_spread: float = float(
        os.getenv("PAPER_MAX_SPREAD", "0.08")
    )
    paper_min_seconds: float = float(
        os.getenv("PAPER_MIN_SECONDS", "10")
    )
    paper_max_seconds: float = float(
        os.getenv("PAPER_MAX_SECONDS", "300")
    )
    paper_min_confidence: float = float(
        os.getenv("PAPER_MIN_CONFIDENCE", "0.25")
    )
    paper_settlement_check_seconds: float = float(
        os.getenv("PAPER_SETTLEMENT_CHECK_SECONDS", "30")
    )
    paper_episode_gap_seconds: float = float(
        os.getenv("PAPER_EPISODE_GAP_SECONDS", "15")
    )
    paper_reentry_cooldown_seconds: float = float(
        os.getenv("PAPER_REENTRY_COOLDOWN_SECONDS", "30")
    )

    min_edge: float = float(os.getenv("MIN_EDGE", "0.02"))
    cost_buffer: float = float(
        os.getenv("COST_BUFFER", "0.01")
    )
    kelly_fraction: float = float(
        os.getenv("KELLY_FRACTION", "0.25")
    )
    max_position_fraction: float = float(
        os.getenv("MAX_POSITION_FRACTION", "0.02")
    )
    daily_loss_limit_fraction: float = float(
        os.getenv("DAILY_LOSS_LIMIT_FRACTION", "0.05")
    )

    def __post_init__(self) -> None:
        """Reject unsafe or contradictory settings before startup."""
        if self.kalshi_env not in {"demo", "production"}:
            raise ValueError(
                "KALSHI_ENV must be either 'demo' or 'production'"
            )

        positive = {
            "PAPER_BANKROLL": self.paper_bankroll,
            "MARKET_DISCOVERY_REFRESH_SECONDS": (
                self.market_discovery_refresh_seconds
            ),
            "MARKET_DISCOVERY_MAX_TARGET_DISTANCE": (
                self.market_discovery_max_target_distance
            ),
            "PAPER_SETTLEMENT_CHECK_SECONDS": (
                self.paper_settlement_check_seconds
            ),
            "PAPER_EPISODE_GAP_SECONDS": self.paper_episode_gap_seconds,
            "PAPER_REENTRY_COOLDOWN_SECONDS": (
                self.paper_reentry_cooldown_seconds
            ),
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        fractions = {
            "PAPER_MIN_CONFIDENCE": (
                self.paper_min_confidence,
                True,
            ),
            "MIN_EDGE": (self.min_edge, True),
            "COST_BUFFER": (self.cost_buffer, True),
            "KELLY_FRACTION": (self.kelly_fraction, True),
            "MAX_POSITION_FRACTION": (
                self.max_position_fraction,
                False,
            ),
            "DAILY_LOSS_LIMIT_FRACTION": (
                self.daily_loss_limit_fraction,
                False,
            ),
        }
        for name, (value, allow_zero) in fractions.items():
            lower_ok = value >= 0 if allow_zero else value > 0
            if not lower_ok or value > 1:
                bound = "[0, 1]" if allow_zero else "(0, 1]"
                raise ValueError(f"{name} must be in {bound}")

        if not (
            0 <= self.market_discovery_max_spread <= 1
            and 0 <= self.paper_max_spread <= 1
        ):
            raise ValueError("Spread limits must be between zero and one")

        if not (
            0 <= self.market_discovery_min_price
            < self.market_discovery_max_price
            <= 1
        ):
            raise ValueError(
                "MARKET_DISCOVERY MIN/MAX PRICE must satisfy "
                "0 <= min < max <= 1"
            )

        if not (
            0 <= self.market_discovery_min_seconds
            < self.market_discovery_max_seconds
        ):
            raise ValueError(
                "MARKET_DISCOVERY MIN/MAX SECONDS must satisfy "
                "0 <= min < max"
            )

        if not (
            0 <= self.paper_min_seconds
            < self.paper_max_seconds
        ):
            raise ValueError(
                "PAPER MIN/MAX SECONDS must satisfy 0 <= min < max"
            )

    @property
    def kalshi_rest_url(self) -> str:
        if self.kalshi_env == "production":
            return (
                "https://external-api.kalshi.com/"
                "trade-api/v2"
            )
        return (
            "https://external-api.demo.kalshi.co/"
            "trade-api/v2"
        )

    @property
    def kalshi_ws_url(self) -> str:
        if self.kalshi_env == "production":
            return (
                "wss://external-api-ws.kalshi.com/"
                "trade-api/ws/v2"
            )
        return (
            "wss://external-api-ws.demo.kalshi.co/"
            "trade-api/ws/v2"
        )
