from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Awaitable, Callable

import websockets
from websockets.exceptions import ConnectionClosed


COINBASE_WS = "wss://advanced-trade-ws.coinbase.com"

TradeCallback = Callable[[dict], Awaitable[None]]


def utc_now() -> str:
    """Return the current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def parse_market_trades(message: dict) -> list[dict]:
    """Extract normalized trades from a Coinbase message."""
    if message.get("channel") != "market_trades":
        return []

    normalized_trades: list[dict] = []

    for event in message.get("events", []):
        for trade in event.get("trades", []):
            price = trade.get("price")
            size = trade.get("size")

            if price is None or size is None:
                continue

            normalized_trades.append(
                {
                    "trade_id": trade.get("trade_id"),
                    "product_id": trade.get("product_id", "BTC-USD"),
                    "timestamp": trade.get("time") or utc_now(),
                    "price": float(price),
                    "size": float(size),
                    "side": trade.get("side"),
                }
            )

    return normalized_trades


async def stream_trades(
    product_id: str,
    callback: TradeCallback,
    reconnect_delay: float = 3.0,
) -> None:
    """
    Stream public Coinbase market trades.

    Automatically reconnect if the WebSocket connection closes or fails.
    """
    while True:
        try:
            print(f"Connecting to Coinbase for {product_id}...")

            async with websockets.connect(
                COINBASE_WS,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
            ) as websocket:
                await websocket.send(
                    json.dumps(
                        {
                            "type": "subscribe",
                            "product_ids": [product_id],
                            "channel": "market_trades",
                        }
                    )
                )

                await websocket.send(
                    json.dumps(
                        {
                            "type": "subscribe",
                            "channel": "heartbeats",
                        }
                    )
                )

                print(f"Connected to Coinbase {product_id}.")
                print("Press Control+C to stop.\n")

                async for raw_message in websocket:
                    message = json.loads(raw_message)

                    for trade in parse_market_trades(message):
                        await callback(trade)

        except asyncio.CancelledError:
            raise

        except (
            ConnectionClosed,
            ConnectionError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
        ) as error:
            print(
                f"Coinbase connection error: {error}\n"
                f"Reconnecting in {reconnect_delay:.1f} seconds..."
            )
            await asyncio.sleep(reconnect_delay)


async def print_trade(trade: dict) -> None:
    """Print a normalized Coinbase trade."""
    side = trade.get("side") or "UNKNOWN"

    print(
        f"{trade['timestamp']} | "
        f"BTC ${trade['price']:,.2f} | "
        f"size {trade['size']:.8f} | "
        f"side {side}"
    )


async def main() -> None:
    await stream_trades(
        product_id="BTC-USD",
        callback=print_trade,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCoinbase feed stopped.")