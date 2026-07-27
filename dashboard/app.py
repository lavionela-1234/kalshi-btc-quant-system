from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import plotly.express as px
import streamlit as st
from kalshi_quant.backtest import metrics

st.set_page_config(page_title="Kalshi BTC Quant", layout="wide")
st.title("Kalshi BTC Quant System")
st.caption("Research and paper-trading dashboard")

tab1, tab2 = st.tabs(["Backtest", "Live snapshots"])

with tab1:
    path = st.text_input("Backtest results CSV", "data/backtest_results.csv")
    if Path(path).exists():
        df = pd.read_csv(path)
        m = metrics(df, float(st.number_input("Starting bankroll", value=1000.0)))
        cols = st.columns(6)
        labels = ["Trades", "Win rate", "Profit", "ROI", "Max drawdown", "EV / trade"]
        vals = [
            m["trades"], f'{m["win_rate"]:.1%}', f'${m["profit"]:,.2f}',
            f'{m["roi"]:.1%}', f'{m["max_drawdown"]:.1%}',
            f'${m["expected_value"]:,.2f}'
        ]
        for c, label, val in zip(cols, labels, vals):
            c.metric(label, val)
        if not df.empty:
            st.plotly_chart(px.line(df, x="timestamp", y="bankroll",
                                    title="Bankroll over time"), use_container_width=True)
            st.plotly_chart(px.area(df, x="timestamp", y="drawdown",
                                    title="Drawdown"), use_container_width=True)
            st.plotly_chart(px.histogram(df, x="pnl", nbins=40,
                                         title="Trade P&L distribution"),
                            use_container_width=True)
            st.dataframe(df.sort_values("timestamp", ascending=False),
                         use_container_width=True)
    else:
        st.info("Run a backtest first or change the path.")

with tab2:
    path = st.text_input("Live snapshots CSV", "data/live_snapshots.csv")
    if Path(path).exists():
        df = pd.read_csv(path)
        latest = df.iloc[-1]
        cols = st.columns(5)
        cols[0].metric("BTC", f'${latest.btc_price:,.2f}')
        cols[1].metric("Distance", f'${latest.distance_usd:+,.2f}')
        cols[2].metric("Time left", f'{latest.seconds_remaining:.0f}s')
        cols[3].metric("Model P(up)", f'{latest.model_p_up:.1%}')
        cols[4].metric("Edge", f'{latest.edge:.1%}')
        st.plotly_chart(px.line(df.tail(1000), x="timestamp",
                                y=["model_p_up", "yes_ask"],
                                title="Model probability vs YES ask"),
                        use_container_width=True)
        st.dataframe(df.tail(200).iloc[::-1], use_container_width=True)
    else:
        st.info("Run the live paper engine first.")
