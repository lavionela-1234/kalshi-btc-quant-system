from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Any
import requests
import websockets
from .auth import KalshiSigner
from .config import Settings

@dataclass
class Book:
    yes: dict[int, int] = field(default_factory=dict)
    no: dict[int, int] = field(default_factory=dict)

    def apply_snapshot(self, payload: dict[str, Any]) -> None:
        self.yes = {int(p): int(q) for p, q in payload.get("yes", [])}
        self.no = {int(p): int(q) for p, q in payload.get("no", [])}

    def apply_delta(self, payload: dict[str, Any]) -> None:
        side = payload["side"]
        price = int(payload["price"])
        delta = int(payload["delta"])
        book = self.yes if side == "yes" else self.no
        new_qty = book.get(price, 0) + delta
        if new_qty <= 0:
            book.pop(price, None)
        else:
            book[price] = new_qty

    @property
    def yes_bid(self) -> float | None:
        return max(self.yes) / 100 if self.yes else None

    @property
    def no_bid(self) -> float | None:
        return max(self.no) / 100 if self.no else None

    @property
    def yes_ask(self) -> float | None:
        return 1 - self.no_bid if self.no_bid is not None else None

    @property
    def no_ask(self) -> float | None:
        return 1 - self.yes_bid if self.yes_bid is not None else None

    def imbalance(self, depth_cents: int = 10) -> float:
        """Top-of-book bid-size imbalance, normalized to [-1, 1]."""
        if not self.yes and not self.no:
            return 0.0
        ybest = max(self.yes) if self.yes else 0
        nbest = max(self.no) if self.no else 0
        yqty = sum(q for p, q in self.yes.items() if p >= ybest - depth_cents)
        nqty = sum(q for p, q in self.no.items() if p >= nbest - depth_cents)
        total = yqty + nqty
        return (yqty - nqty) / total if total else 0.0

class KalshiREST:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.signer = None
        if settings.kalshi_api_key_id and settings.kalshi_private_key_path:
            self.signer = KalshiSigner(
                settings.kalshi_api_key_id, settings.kalshi_private_key_path
            )

    def _get(self, path: str, params: dict | None = None, auth: bool = False) -> dict:
        url = self.settings.kalshi_rest_url + path
        headers = self.signer.headers("GET", url) if auth and self.signer else {}
        response = requests.get(url, params=params, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()

    def market(self, ticker: str) -> dict:
        return self._get(f"/markets/{ticker}")["market"]

    def markets(self, **params) -> list[dict]:
        return self._get("/markets", params=params).get("markets", [])

    def orderbook(self, ticker: str, depth: int = 0) -> Book:
        data = self._get(f"/markets/{ticker}/orderbook", params={"depth": depth})
        raw = data.get("orderbook", data)
        book = Book()
        book.apply_snapshot(raw)
        return book

    def balance(self) -> dict:
        return self._get("/portfolio/balance", auth=True)

class KalshiWS:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.signer = KalshiSigner(
            settings.kalshi_api_key_id, settings.kalshi_private_key_path
        )

    async def stream_orderbook(
        self,
        ticker: str,
        callback: Callable[[Book, dict], Awaitable[None]],
    ) -> None:
        headers = self.signer.headers("GET", "/trade-api/ws/v2")
        book = Book()
        async with websockets.connect(
            self.settings.kalshi_ws_url,
            additional_headers=headers,
            ping_interval=None,
        ) as ws:
            await ws.send(json.dumps({
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": [ticker],
                },
            }))
            async for raw in ws:
                msg = json.loads(raw)
                typ = msg.get("type")
                payload = msg.get("msg", {})
                if typ == "orderbook_snapshot":
                    book.apply_snapshot(payload)
                    await callback(book, msg)
                elif typ == "orderbook_delta":
                    book.apply_delta(payload)
                    await callback(book, msg)
