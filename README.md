# Kalshi BTC Quant System

A research-first, paper-trading system for short-duration Kalshi Bitcoin event contracts.

## What it does

- Connects to Kalshi REST market data and authenticated WebSockets.
- Streams BTC-USD trades from Coinbase Advanced Trade.
- Calculates distance to strike, realized volatility, trend, momentum, time remaining, and Kalshi order-book imbalance.
- Estimates settlement probability with:
  1. a transparent volatility model available immediately, and
  2. a trainable historical logistic-regression model.
- Flags a trade only when model edge exceeds configurable transaction-cost and safety buffers.
- Includes fixed-risk and fractional-Kelly sizing.
- Includes a CSV backtesting engine and Streamlit dashboard.
- Defaults to **paper mode**. It does not place live orders automatically.

## Important model limitation

The correct BTC reference feed and settlement rules must match the exact Kalshi market. Coinbase BTC-USD is included as a convenient live signal, but it may differ from Kalshi’s official settlement source. Verify the market rules before relying on the signal.

## Quick start

```bash
cd kalshi_btc_quant_system
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Add your Kalshi API key ID and private-key path to `.env`. Start with Kalshi’s demo environment.

Run the live paper-trading engine:

```bash
python -m kalshi_quant.cli live --ticker YOUR_MARKET_TICKER --target 64028.26
```

Run a backtest:

```bash
python -m kalshi_quant.cli backtest \
  --csv data/sample_backtest.csv \
  --bankroll 1000 \
  --output data/backtest_results.csv
```

Open the dashboard:

```bash
streamlit run dashboard/app.py
```

## Input CSV schema

Each row is one decision snapshot:

```text
timestamp,market_ticker,btc_price,target_price,seconds_remaining,
yes_bid,yes_ask,no_bid,no_ask,yes_bid_size,no_bid_size,
ret_5s,ret_15s,ret_60s,rv_60s,rv_300s,trend_ema,settled_up
```

`settled_up` is 1 when BTC settled above the market target and 0 otherwise.

## Recommended workflow

1. Collect live snapshots in paper mode.
2. Add verified settlement outcomes.
3. Backtest with walk-forward splits.
4. Calibrate the model.
5. Paper trade for several weeks.
6. Use Kalshi demo execution before considering production.
7. Keep production order placement behind a manual confirmation and hard daily-loss limit.

## Risk controls

The default configuration includes:

- 2 percentage-point minimum model edge.
- Additional fee/slippage buffer.
- 0.25 fractional Kelly.
- 1% fixed-risk alternative.
- 2% maximum bankroll exposure per position.
- 5% daily-loss stop.
- Maximum one open signal per market.
- No signal when the spread or data age exceeds limits.

This is research software, not a guarantee of profit.
