from __future__ import annotations
from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    kalshi_env: str = os.getenv("KALSHI_ENV", "demo")
    kalshi_api_key_id: str = os.getenv("KALSHI_API_KEY_ID", "")
    kalshi_private_key_path: str = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    coinbase_product_id: str = os.getenv("COINBASE_PRODUCT_ID", "BTC-USD")
    paper_mode: bool = os.getenv("PAPER_MODE", "true").lower() == "true"
    min_edge: float = float(os.getenv("MIN_EDGE", "0.02"))
    cost_buffer: float = float(os.getenv("COST_BUFFER", "0.01"))
    kelly_fraction: float = float(os.getenv("KELLY_FRACTION", "0.25"))
    max_position_fraction: float = float(os.getenv("MAX_POSITION_FRACTION", "0.02"))
    daily_loss_limit_fraction: float = float(os.getenv("DAILY_LOSS_LIMIT_FRACTION", "0.05"))

    @property
    def kalshi_rest_url(self) -> str:
        if self.kalshi_env == "production":
            return "https://external-api.kalshi.com/trade-api/v2"
        return "https://external-api.demo.kalshi.co/trade-api/v2"

    @property
    def kalshi_ws_url(self) -> str:
        if self.kalshi_env == "production":
            return "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
        return "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
