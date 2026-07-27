from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from typing import Callable, Awaitable
import websockets

COINBASE_WS = "wss://advanced-trade-ws.coinbase.com"

async def stream_trades(
    product_id: str,
    callback: Callable[[dict], Awaitable[None]],
) -> None:
    """Public Coinbase Advanced Trade market-trades stream."""
    async with websockets.connect(COINBASE_WS, ping_interval=20) as ws:
        await ws.send(json.dumps({
            "type": "subscribe",
            "product_ids": [product_id],
            "channel": "market_trades",
        }))
        await ws.send(json.dumps({
            "type": "subscribe",
            "product_ids": [product_id],
            "channel": "heartbeats",
        }))
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("channel") != "market_trades":
                continue
            for event in msg.get("events", []):
                for trade in event.get("trades", []):
                    await callback({
                        "timestamp": trade.get("time", datetime.now(timezone.utc).isoformat()),
                        "price": float(trade["price"]),
                        "size": float(trade["size"]),
                        "side": trade.get("side"),
                    })
