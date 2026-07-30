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
