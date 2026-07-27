from __future__ import annotations
import asyncio
import csv
from datetime import datetime, timezone
from pathlib import Path
from .coinbase import stream_trades
from .config import Settings
from .features import RollingBTCFeatures
from .kalshi import KalshiREST
from .model import ProbabilityModel
from .signal import evaluate_signal
from .risk import fractional_kelly

class LivePaperEngine:
    def __init__(self, ticker: str, target: float, bankroll: float, settings: Settings,
                 model_path: str | None = None):
        self.ticker = ticker
        self.target = target
        self.bankroll = bankroll
        self.settings = settings
        self.rest = KalshiREST(settings)
        self.features = RollingBTCFeatures()
        self.model = ProbabilityModel.load(model_path) if model_path else ProbabilityModel()
        self.last_price = None
        self.close_time = None
        self.output = Path("data/live_snapshots.csv")
        self.output.parent.mkdir(exist_ok=True)

    def load_market(self):
        market = self.rest.market(self.ticker)
        close_raw = market.get("close_time") or market.get("expected_expiration_time")
        if not close_raw:
            raise ValueError("Market response did not include close_time.")
        self.close_time = datetime.fromisoformat(close_raw.replace("Z", "+00:00"))

    def write(self, row: dict):
        exists = self.output.exists()
        with self.output.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=row.keys())
            if not exists:
                w.writeheader()
            w.writerow(row)

    async def on_trade(self, trade: dict):
        now = datetime.fromisoformat(trade["timestamp"].replace("Z", "+00:00"))
        price = trade["price"]
        self.features.add(now, price)
        self.last_price = price
        book = self.rest.orderbook(self.ticker)
        feat = self.features.snapshot(
            now, price, self.target, self.close_time, book.imbalance()
        )
        p_up = self.model.predict_up(feat)
        sig = evaluate_signal(
            feat, p_up, book.yes_ask, book.no_ask,
            self.settings.min_edge, self.settings.cost_buffer
        )
        sizing = None
        if sig.action == "FLAG":
            contract_price = book.yes_ask if sig.side == "YES" else book.no_ask
            side_p = p_up if sig.side == "YES" else 1-p_up
            sizing = fractional_kelly(
                self.bankroll, side_p, contract_price,
                self.settings.kelly_fraction, self.settings.max_position_fraction
            )
        row = {
            "timestamp": now.isoformat(), "market_ticker": self.ticker,
            **feat.__dict__,
            "yes_bid": book.yes_bid, "yes_ask": book.yes_ask,
            "no_bid": book.no_bid, "no_ask": book.no_ask,
            "model_p_up": p_up, "signal": sig.action, "side": sig.side,
            "edge": sig.edge,
            "recommended_contracts": sizing.contracts if sizing else 0,
        }
        self.write(row)
        print(
            f"{now:%H:%M:%S} BTC={price:.2f} d={feat.distance_usd:+.2f} "
            f"t={feat.seconds_remaining:.0f}s pUp={p_up:.3f} "
            f"YESask={book.yes_ask} signal={sig.action} {sig.side or ''} "
            f"edge={sig.edge:.3f}"
        )

    async def run(self):
        self.load_market()
        await stream_trades(self.settings.coinbase_product_id, self.on_trade)
