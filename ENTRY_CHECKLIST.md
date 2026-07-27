# Entry and Exit Checklist

## Entry gate

A signal is eligible only when all boxes are true:

- [ ] Exact Kalshi ticker and target are verified.
- [ ] Settlement source/rules are reviewed.
- [ ] BTC feed is fresh.
- [ ] Kalshi order book is fresh.
- [ ] 10–300 seconds remain.
- [ ] Bid/ask spread is no wider than configured.
- [ ] Model edge exceeds `MIN_EDGE + COST_BUFFER`.
- [ ] Position size is below the per-position cap.
- [ ] Daily loss stop has not been reached.
- [ ] No duplicate position exists in the market.
- [ ] No known scheduled high-impact event is imminent.
- [ ] Paper/demo mode is being used during validation.

## Exit logic

Binary contracts normally settle at $1 or $0. A pre-settlement exit should be used only when:

- model edge becomes materially negative;
- the live data feed is stale or disconnected;
- a hard risk control is triggered;
- liquidity allows an exit without excessive slippage.

Do not use an arbitrary profit target without backtesting it. Exit logic must be tested with executable bid prices, not midpoint prices.
