from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .features import FeatureSnapshot
from .model import ProbabilityModel
from .signal import evaluate_signal
from .risk import fractional_kelly, fixed_risk

@dataclass
class BacktestConfig:
    starting_bankroll: float = 1000.0
    min_edge: float = 0.02
    cost_buffer: float = 0.01
    sizing: str = "kelly"
    kelly_fraction: float = 0.25
    fixed_risk_fraction: float = 0.01
    max_position_fraction: float = 0.02
    fee_per_contract: float = 0.0

def _row_feature(r) -> FeatureSnapshot:
    return FeatureSnapshot(
        btc_price=float(r.btc_price),
        target_price=float(r.target_price),
        distance_usd=float(r.btc_price-r.target_price),
        distance_bps=float((r.btc_price-r.target_price)/r.target_price*10000),
        seconds_remaining=float(r.seconds_remaining),
        ret_5s=float(r.ret_5s), ret_15s=float(r.ret_15s), ret_60s=float(r.ret_60s),
        rv_60s=float(r.rv_60s), rv_300s=float(r.rv_300s),
        trend_ema=float(r.trend_ema),
        momentum=float(getattr(r, "momentum", .5*r.ret_5s+.3*r.ret_15s+.2*r.ret_60s)),
        orderbook_imbalance=float(
            getattr(r, "orderbook_imbalance",
                    (r.yes_bid_size-r.no_bid_size)/(r.yes_bid_size+r.no_bid_size)
                    if r.yes_bid_size+r.no_bid_size else 0)
        ),
    )

def run_backtest(df: pd.DataFrame, model: ProbabilityModel, cfg: BacktestConfig) -> pd.DataFrame:
    df = df.sort_values("timestamp").copy()
    bankroll = cfg.starting_bankroll
    peak = bankroll
    records = []
    traded_markets = set()

    for r in df.itertuples(index=False):
        if r.market_ticker in traded_markets:
            continue
        f = _row_feature(r)
        p_up = model.predict_up(f)
        sig = evaluate_signal(
            f, p_up, float(r.yes_ask), float(r.no_ask),
            cfg.min_edge, cfg.cost_buffer
        )
        if sig.action != "FLAG":
            continue

        price = float(r.yes_ask if sig.side == "YES" else r.no_ask)
        probability = p_up if sig.side == "YES" else 1-p_up
        if cfg.sizing == "fixed":
            rd = fixed_risk(bankroll, price, cfg.fixed_risk_fraction,
                            cfg.max_position_fraction)
        else:
            rd = fractional_kelly(bankroll, probability, price,
                                  cfg.kelly_fraction, cfg.max_position_fraction)
        if rd.blocked:
            continue

        won = bool(r.settled_up) if sig.side == "YES" else not bool(r.settled_up)
        pnl = rd.contracts*((1-price) if won else -price) - rd.contracts*cfg.fee_per_contract
        bankroll += pnl
        peak = max(peak, bankroll)
        drawdown = (bankroll-peak)/peak
        traded_markets.add(r.market_ticker)
        records.append({
            "timestamp": r.timestamp,
            "market_ticker": r.market_ticker,
            "side": sig.side,
            "model_probability": probability,
            "entry_price": price,
            "edge": sig.edge,
            "contracts": rd.contracts,
            "stake": rd.stake_dollars,
            "won": won,
            "pnl": pnl,
            "bankroll": bankroll,
            "drawdown": drawdown,
        })
    return pd.DataFrame(records)

def metrics(results: pd.DataFrame, starting_bankroll: float) -> dict:
    if results.empty:
        return {"trades": 0, "win_rate": 0, "profit": 0, "roi": 0,
                "max_drawdown": 0, "avg_edge": 0, "expected_value": 0}
    return {
        "trades": int(len(results)),
        "win_rate": float(results.won.mean()),
        "profit": float(results.pnl.sum()),
        "roi": float(results.pnl.sum()/starting_bankroll),
        "max_drawdown": float(results.drawdown.min()),
        "avg_edge": float(results.edge.mean()),
        "expected_value": float(results.pnl.mean()),
    }
