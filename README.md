# Kalshi BTC Quant System

A research-first system for collecting Bitcoin market data, generating
technical signals, discovering compatible Kalshi BTC markets, and evaluating
those signals through paper trading.

> **Safety status:** The repository's `develop` branch simulates trades only.
> It does not contain a production order-placement implementation.

## Current architecture

The development branch includes:

- Coinbase BTC-USD trade recording with SQLite deduplication.
- 1-second, 5-second, and 60-second market-bar construction.
- EMA, VWAP, RSI, volatility, momentum, and order-flow indicators.
- Automatic technical-signal generation on completed bars.
- Discovery and rollover for compatible Kalshi BTC markets.
- Paper-entry gates for direction, confidence, spread, time remaining,
  duplicate episodes, reentry cooldown, and daily loss.
- Paper-trade settlement, bankroll accounting, and calibration reports.
- A Streamlit dashboard for recorder health, signals, markets, paper trades,
  settlement, and calibration.

The system stores operational state in `data/kalshi_quant.sqlite3`.

## Important model limitation

Coinbase BTC-USD is a convenient signal feed, but it may differ from the
reference and settlement source specified by an individual Kalshi market.
Always verify the exact market rules and settlement source. Paper performance
does not establish that a strategy will remain profitable with real fees,
latency, liquidity, or slippage.

## Installation

```bash
git clone https://github.com/lavionela-1234/kalshi-btc-quant-system.git
cd kalshi-btc-quant-system
git switch develop
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
cp .env.example .env
```

Add the Kalshi API key ID and the absolute private-key path to `.env`.
Keep `KALSHI_ENV=demo` and `PAPER_MODE=true` while validating the system.

## Verification

Run the entire test suite:

```bash
python -m pytest -q
```

Compile the source and dashboard:

```bash
python -m compileall -q src dashboard
```

GitHub Actions runs both checks on pull requests and pushes to `develop` or
`main` using Python 3.11 and 3.12.

## Dashboard

```bash
streamlit run dashboard/app.py
```

The dashboard reads the local SQLite database. The recorder and signal
pipeline must be running before live market panels populate.

## Configuration safeguards

Settings are validated at process startup. The application refuses invalid
environments, nonpositive bankrolls or intervals, percentages outside their
safe ranges, inverted time windows, and invalid discovery price bounds.

SQLite uses foreign keys, WAL journaling, a five-second busy timeout,
transaction rollback on failure, and an explicit schema-version record.

## Branches

- `main`: stable releases.
- `develop`: integrated development.
- Feature and stabilization work should enter through reviewed pull requests.

Do not merge a branch into `main` until CI passes and any locally running bot
has been compared with the GitHub code.

## Before any future live execution

A separate, reviewed execution layer should require all of the following:

- Explicit production confirmation.
- BTC-series allowlist.
- Maximum order dollars and maximum open positions.
- Persistent daily-loss circuit breaker and kill switch.
- Stale-data and disconnected-feed shutdown.
- Idempotent client order IDs.
- Exchange-position and fill reconciliation.
- Fee, partial-fill, and slippage accounting.
- Restart and crash-recovery tests.

This is research software, not financial advice or a guarantee of profit.
