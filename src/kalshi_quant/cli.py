from __future__ import annotations
import argparse
import asyncio
import pandas as pd
from .backtest import BacktestConfig, metrics, run_backtest
from .config import Settings
from .live import LivePaperEngine
from .model import ProbabilityModel, train_model

def main():
    p = argparse.ArgumentParser(prog="kalshi-quant")
    sub = p.add_subparsers(dest="cmd", required=True)

    live = sub.add_parser("live")
    live.add_argument("--ticker", required=True)
    live.add_argument("--target", required=True, type=float)
    live.add_argument("--bankroll", type=float, default=1000)
    live.add_argument("--model")

    train = sub.add_parser("train")
    train.add_argument("--csv", required=True)
    train.add_argument("--output", default="data/model.joblib")

    bt = sub.add_parser("backtest")
    bt.add_argument("--csv", required=True)
    bt.add_argument("--model")
    bt.add_argument("--bankroll", type=float, default=1000)
    bt.add_argument("--output", default="data/backtest_results.csv")
    bt.add_argument("--sizing", choices=["kelly", "fixed"], default="kelly")

    args = p.parse_args()
    if args.cmd == "live":
        engine = LivePaperEngine(args.ticker, args.target, args.bankroll,
                                 Settings(), args.model)
        asyncio.run(engine.run())
    elif args.cmd == "train":
        df = pd.read_csv(args.csv)
        model = train_model(df)
        model.save(args.output)
        print(f"Saved model to {args.output}")
    elif args.cmd == "backtest":
        df = pd.read_csv(args.csv)
        model = ProbabilityModel.load(args.model) if args.model else ProbabilityModel()
        cfg = BacktestConfig(starting_bankroll=args.bankroll, sizing=args.sizing)
        results = run_backtest(df, model, cfg)
        results.to_csv(args.output, index=False)
        print(metrics(results, args.bankroll))
        print(f"Saved results to {args.output}")

if __name__ == "__main__":
    main()
