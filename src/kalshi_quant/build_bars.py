from __future__ import annotations

import argparse

from .bars import (
    bar_count,
    build_bars_from_database,
    latest_bar,
)


SUPPORTED_INTERVALS = (1, 5, 60)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build Coinbase market bars from recorded trades."
        )
    )

    parser.add_argument(
        "--interval",
        type=int,
        choices=SUPPORTED_INTERVALS,
        default=60,
        help="Bar interval in seconds: 1, 5, or 60.",
    )

    parser.add_argument(
        "--product",
        default="BTC-USD",
        help="Coinbase product ID.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Use only the most recent N trades.",
    )

    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()

    created = build_bars_from_database(
        interval_seconds=arguments.interval,
        product_id=arguments.product,
        trade_limit=arguments.limit,
    )

    total = bar_count(
        interval_seconds=arguments.interval,
        product_id=arguments.product,
    )

    latest = latest_bar(
        interval_seconds=arguments.interval,
        product_id=arguments.product,
    )

    print("Kalshi BTC Quant System — Market Bars")
    print(f"Product:  {arguments.product}")
    print(f"Interval: {arguments.interval} seconds")
    print(f"Bars processed: {created:,}")
    print(f"Bars stored:    {total:,}")

    if latest is not None:
        print()
        print("Latest bar")
        print(f"Start:     {latest['start_time']}")
        print(f"Open:      ${latest['open']:,.2f}")
        print(f"High:      ${latest['high']:,.2f}")
        print(f"Low:       ${latest['low']:,.2f}")
        print(f"Close:     ${latest['close']:,.2f}")
        print(f"Volume:    {latest['volume']:.8f} BTC")
        print(f"Trades:    {latest['trade_count']:,}")
        print(
            "Imbalance: "
            f"{latest['volume_imbalance']:+.4f}"
        )


if __name__ == "__main__":
    main()