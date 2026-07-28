from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "src"),
)

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from kalshi_quant.backtest import metrics
from kalshi_quant.dashboard_data import (
    market_summary,
    recent_bars,
    recent_trades,
)
from kalshi_quant.indicators import add_market_indicators
from kalshi_quant.market_signal import evaluate_market_signal

st.set_page_config(
    page_title="Kalshi BTC Quant",
    page_icon="₿",
    layout="wide",
)

st.title("Kalshi BTC Quant System")
st.caption(
    "Coinbase market data, quantitative research, "
    "backtesting, and paper trading"
)

tab1, tab2, tab3 = st.tabs(
    [
        "Coinbase Market",
        "Backtest",
        "Live Snapshots",
    ]
)


with tab1:
    controls = st.columns([2, 2, 2, 1])

    product_id = controls[0].selectbox(
        "Product",
        ["BTC-USD"],
    )

    interval_seconds = controls[1].selectbox(
        "Bar interval",
        options=[1, 5, 60],
        index=2,
        format_func=lambda value: {
            1: "1 second",
            5: "5 seconds",
            60: "1 minute",
        }[value],
    )

    bar_limit = controls[2].selectbox(
        "Bars displayed",
        options=[50, 100, 200, 300, 500],
        index=2,
    )

    controls[3].write("")
    controls[3].write("")

    if controls[3].button(
        "Refresh",
        width="stretch",
    ):
        st.rerun()

    summary = market_summary(
        product_id=product_id,
        interval_seconds=interval_seconds,
    )

    bars = recent_bars(
        product_id=product_id,
        interval_seconds=interval_seconds,
        limit=bar_limit,
    )

    latest_trade = summary["latest_trade"]

    latest_price = (
        float(latest_trade["price"])
        if latest_trade is not None
        else None
    )

    if bars.empty:
        st.warning(
            "No market bars are available for this interval. "
            "Run the Coinbase recorder and bar builder first."
        )

        st.subheader("Recent Coinbase trades")

        trades = recent_trades(
            product_id=product_id,
            limit=200,
        )

        if trades.empty:
            st.info("No Coinbase trades have been recorded.")
        else:
            display_trades = trades.copy()

            display_trades["timestamp"] = (
                display_trades["timestamp"]
                .dt.strftime("%Y-%m-%d %H:%M:%S.%f UTC")
            )

            display_trades["price"] = (
                display_trades["price"]
                .astype(float)
                .map(lambda value: f"${value:,.2f}")
            )

            display_trades["size"] = (
                display_trades["size"]
                .astype(float)
                .map(lambda value: f"{value:.8f}")
            )

            st.dataframe(
                display_trades,
                width="stretch",
                hide_index=True,
            )

    else:
        try:
            technical_signal = evaluate_market_signal(bars)
            signal_error = None
        except ValueError as exc:
            technical_signal = None
            signal_error = str(exc)

        bars = add_market_indicators(bars)

        latest_bar = bars.iloc[-1]

        previous_close = (
            float(bars.iloc[-2]["close"])
            if len(bars) >= 2
            else float(latest_bar["open"])
        )

        latest_close = float(latest_bar["close"])

        price_change = latest_close - previous_close

        price_change_percent = (
            price_change / previous_close
            if previous_close != 0
            else 0.0
        )

        latest_vwap = float(latest_bar["vwap"])
        latest_rsi = float(latest_bar["rsi_14"])
        latest_volatility = latest_bar["volatility_20"]

        volatility_display = (
            f"{float(latest_volatility):.3%}"
            if pd.notna(latest_volatility)
            else "Collecting data"
        )

        trade_rate = (
            float(latest_bar["trade_count"])
            / interval_seconds
        )

        st.markdown(
            f"""
            ### {product_id} · LIVE

            **Latest market update:**  
            {latest_bar["start_time"]}
            """
        )

        st.subheader("Technical market signal")

        if technical_signal is None:
            st.info(
                "Technical signal unavailable: "
                f"{signal_error or 'Insufficient market data.'}"
            )
        else:
            signal_kpis = st.columns(6)

            signal_kpis[0].metric(
                "Direction",
                technical_signal.direction,
            )

            signal_kpis[1].metric(
                "Action",
                technical_signal.action.replace("_", " "),
            )

            signal_kpis[2].metric(
                "Composite score",
                f"{technical_signal.score:+.1f}",
            )

            signal_kpis[3].metric(
                "Technical P(up)",
                f"{technical_signal.probability_up:.1%}",
            )

            signal_kpis[4].metric(
                "Confidence",
                f"{technical_signal.confidence:.1%}",
            )

            signal_kpis[5].metric(
                "Volatility regime",
                technical_signal.volatility_regime,
            )

            st.caption(technical_signal.reason)

            component_data = pd.DataFrame(
                {
                    "Component": [
                        "Trend",
                        "Momentum",
                        "VWAP",
                        "RSI",
                        "Order flow",
                    ],
                    "Score": [
                        technical_signal.trend_score,
                        technical_signal.momentum_score,
                        technical_signal.vwap_score,
                        technical_signal.rsi_score,
                        technical_signal.order_flow_score,
                    ],
                }
            )

            component_chart = go.Figure(
                go.Bar(
                    x=component_data["Component"],
                    y=component_data["Score"],
                    text=[
                        f"{value:+.1f}"
                        for value in component_data["Score"]
                    ],
                    textposition="auto",
                    name="Component score",
                )
            )

            component_chart.add_hline(
                y=0,
                line_dash="dash",
            )

            component_chart.update_layout(
                title="Technical signal components",
                xaxis_title="Component",
                yaxis_title="Bullish / bearish contribution",
                height=350,
                showlegend=False,
            )

            st.plotly_chart(
                component_chart,
                width="stretch",
            )

            st.caption(
                "Technical research signal only. The final Kalshi "
                "trade decision must still pass order-book edge, "
                "spread, time-window, and risk checks."
            )

        st.divider()

        kpi_row_one = st.columns(6)

        kpi_row_one[0].metric(
            "BTC price",
            (
                f"${latest_price:,.2f}"
                if latest_price is not None
                else f"${latest_close:,.2f}"
            ),
            delta=(
                f"{price_change:+,.2f} "
                f"({price_change_percent:+.2%})"
            ),
        )

        kpi_row_one[1].metric(
            "VWAP",
            f"${latest_vwap:,.2f}",
            delta=(
                f"{latest_close - latest_vwap:+,.2f} "
                "vs. price"
            ),
        )

        kpi_row_one[2].metric(
            "RSI 14",
            f"{latest_rsi:.1f}",
        )

        kpi_row_one[3].metric(
            "Volatility 20",
            volatility_display,
        )

        kpi_row_one[4].metric(
            "Trades per second",
            f"{trade_rate:,.2f}",
        )

        kpi_row_one[5].metric(
            "Volume imbalance",
            f'{float(latest_bar["volume_imbalance"]):+.1%}',
        )

        kpi_row_two = st.columns(6)

        kpi_row_two[0].metric(
            "Open",
            f'${float(latest_bar["open"]):,.2f}',
        )

        kpi_row_two[1].metric(
            "High",
            f'${float(latest_bar["high"]):,.2f}',
        )

        kpi_row_two[2].metric(
            "Low",
            f'${float(latest_bar["low"]):,.2f}',
        )

        kpi_row_two[3].metric(
            "Close",
            f'${float(latest_bar["close"]):,.2f}',
        )

        kpi_row_two[4].metric(
            "Volume",
            f'{float(latest_bar["volume"]):,.6f} BTC',
        )

        kpi_row_two[5].metric(
            "Recorded trades",
            f'{summary["trade_count"]:,}',
        )

        st.divider()

        price_chart = go.Figure()

        price_chart.add_trace(
            go.Candlestick(
                x=bars["start_time"],
                open=bars["open"],
                high=bars["high"],
                low=bars["low"],
                close=bars["close"],
                name=product_id,
            )
        )

        price_chart.add_trace(
            go.Scatter(
                x=bars["start_time"],
                y=bars["ema_9"],
                mode="lines",
                name="EMA 9",
                line={"width": 1.5},
            )
        )

        price_chart.add_trace(
            go.Scatter(
                x=bars["start_time"],
                y=bars["ema_20"],
                mode="lines",
                name="EMA 20",
                line={"width": 1.5},
            )
        )

        price_chart.add_trace(
            go.Scatter(
                x=bars["start_time"],
                y=bars["ema_50"],
                mode="lines",
                name="EMA 50",
                line={"width": 1.5},
            )
        )

        price_chart.add_trace(
            go.Scatter(
                x=bars["start_time"],
                y=bars["vwap"],
                mode="lines",
                name="VWAP",
                line={
                    "width": 2,
                    "dash": "dot",
                },
            )
        )

        price_chart.update_layout(
            title=(
                f"{product_id} price, moving averages, and VWAP"
            ),
            xaxis_title="Time",
            yaxis_title="Price (USD)",
            xaxis_rangeslider_visible=False,
            height=650,
            hovermode="x unified",
            legend={
                "orientation": "h",
                "yanchor": "bottom",
                "y": 1.02,
                "xanchor": "left",
                "x": 0,
            },
        )

        st.plotly_chart(
            price_chart,
            width="stretch",
        )

        volume_chart = go.Figure()

        volume_chart.add_trace(
            go.Bar(
                x=bars["start_time"],
                y=bars["buy_volume"],
                name="Buy volume",
            )
        )

        volume_chart.add_trace(
            go.Bar(
                x=bars["start_time"],
                y=bars["sell_volume"],
                name="Sell volume",
            )
        )

        volume_chart.update_layout(
            title="Buy and sell volume",
            xaxis_title="Time",
            yaxis_title="BTC volume",
            barmode="stack",
            height=350,
            hovermode="x unified",
        )

        st.plotly_chart(
            volume_chart,
            width="stretch",
        )

        lower_left, lower_right = st.columns(2)

        rsi_chart = go.Figure()

        rsi_chart.add_trace(
            go.Scatter(
                x=bars["start_time"],
                y=bars["rsi_14"],
                mode="lines",
                name="RSI 14",
            )
        )

        rsi_chart.add_hline(
            y=70,
            line_dash="dash",
            annotation_text="Overbought 70",
        )

        rsi_chart.add_hline(
            y=30,
            line_dash="dash",
            annotation_text="Oversold 30",
        )

        rsi_chart.add_hline(
            y=50,
            line_dash="dot",
        )

        rsi_chart.update_layout(
            title="Relative Strength Index",
            xaxis_title="Time",
            yaxis_title="RSI",
            yaxis={
                "range": [0, 100],
            },
            height=350,
            showlegend=False,
        )

        lower_left.plotly_chart(
            rsi_chart,
            width="stretch",
        )

        volatility_chart = go.Figure()

        volatility_chart.add_trace(
            go.Scatter(
                x=bars["start_time"],
                y=bars["volatility_20"] * 100,
                mode="lines",
                fill="tozeroy",
                name="Rolling volatility",
            )
        )

        volatility_chart.update_layout(
            title="Rolling 20-bar volatility",
            xaxis_title="Time",
            yaxis_title="Volatility (%)",
            height=350,
            showlegend=False,
        )

        lower_right.plotly_chart(
            volatility_chart,
            width="stretch",
        )

        flow_left, flow_right = st.columns(2)

        imbalance_chart = go.Figure()

        imbalance_chart.add_trace(
            go.Scatter(
                x=bars["start_time"],
                y=bars["volume_imbalance"],
                mode="lines",
                fill="tozeroy",
                name="Volume imbalance",
            )
        )

        imbalance_chart.add_hline(
            y=0,
            line_dash="dash",
        )

        imbalance_chart.update_layout(
            title="Order-flow imbalance",
            xaxis_title="Time",
            yaxis_title="Imbalance",
            yaxis={
                "range": [-1, 1],
            },
            height=350,
            showlegend=False,
        )

        flow_left.plotly_chart(
            imbalance_chart,
            width="stretch",
        )

        pressure_chart = go.Figure()

        pressure_chart.add_trace(
            go.Scatter(
                x=bars["start_time"],
                y=bars["buy_pressure"] * 100,
                mode="lines",
                name="Buy pressure",
            )
        )

        pressure_chart.add_trace(
            go.Scatter(
                x=bars["start_time"],
                y=bars["sell_pressure"] * 100,
                mode="lines",
                name="Sell pressure",
            )
        )

        pressure_chart.update_layout(
            title="Buy and sell pressure",
            xaxis_title="Time",
            yaxis_title="Share of volume (%)",
            height=350,
            hovermode="x unified",
        )

        flow_right.plotly_chart(
            pressure_chart,
            width="stretch",
        )

        st.subheader("Recent market bars")

        display_bars = bars[
            [
                "start_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "trade_count",
                "ema_9",
                "ema_20",
                "ema_50",
                "vwap",
                "rsi_14",
                "volatility_20",
                "volume_imbalance",
            ]
        ].copy()

        display_bars["start_time"] = (
            display_bars["start_time"]
            .dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        )

        st.dataframe(
            display_bars.iloc[::-1],
            width="stretch",
            hide_index=True,
        )

        st.subheader("Live trade tape")

        trades = recent_trades(
            product_id=product_id,
            limit=200,
        )

        if trades.empty:
            st.info("No Coinbase trades have been recorded.")
        else:
            display_trades = trades.copy()

            display_trades["timestamp"] = (
                display_trades["timestamp"]
                .dt.strftime("%H:%M:%S.%f")
            )

            display_trades["price"] = (
                display_trades["price"]
                .astype(float)
                .map(lambda value: f"${value:,.2f}")
            )

            display_trades["size"] = (
                display_trades["size"]
                .astype(float)
                .map(lambda value: f"{value:.8f}")
            )

            st.dataframe(
                display_trades,
                width="stretch",
                hide_index=True,
            )


with tab2:
    path = st.text_input(
        "Backtest results CSV",
        "data/backtest_results.csv",
    )

    if Path(path).exists():
        dataframe = pd.read_csv(path)

        starting_bankroll = float(
            st.number_input(
                "Starting bankroll",
                value=1000.0,
            )
        )

        report = metrics(
            dataframe,
            starting_bankroll,
        )

        metric_columns = st.columns(6)

        labels = [
            "Trades",
            "Win rate",
            "Profit",
            "ROI",
            "Max drawdown",
            "EV / trade",
        ]

        values = [
            report["trades"],
            f'{report["win_rate"]:.1%}',
            f'${report["profit"]:,.2f}',
            f'{report["roi"]:.1%}',
            f'{report["max_drawdown"]:.1%}',
            f'${report["expected_value"]:,.2f}',
        ]

        for column, label, value in zip(
            metric_columns,
            labels,
            values,
        ):
            column.metric(label, value)

        if not dataframe.empty:
            st.plotly_chart(
                px.line(
                    dataframe,
                    x="timestamp",
                    y="bankroll",
                    title="Bankroll over time",
                ),
                width="stretch",
            )

            st.plotly_chart(
                px.area(
                    dataframe,
                    x="timestamp",
                    y="drawdown",
                    title="Drawdown",
                ),
                width="stretch",
            )

            st.plotly_chart(
                px.histogram(
                    dataframe,
                    x="pnl",
                    nbins=40,
                    title="Trade P&L distribution",
                ),
                width="stretch",
            )

            st.dataframe(
                dataframe.sort_values(
                    "timestamp",
                    ascending=False,
                ),
                width="stretch",
            )
    else:
        st.info(
            "Run a backtest first or change the CSV path."
        )


with tab3:
    path = st.text_input(
        "Live snapshots CSV",
        "data/live_snapshots.csv",
    )

    if Path(path).exists():
        dataframe = pd.read_csv(path)

        if dataframe.empty:
            st.info("The live snapshots file is empty.")
        else:
            latest = dataframe.iloc[-1]
            metric_columns = st.columns(5)

            metric_columns[0].metric(
                "BTC",
                f"${latest.btc_price:,.2f}",
            )
            metric_columns[1].metric(
                "Distance",
                f"${latest.distance_usd:+,.2f}",
            )
            metric_columns[2].metric(
                "Time left",
                f"{latest.seconds_remaining:.0f}s",
            )
            metric_columns[3].metric(
                "Model P(up)",
                f"{latest.model_p_up:.1%}",
            )
            metric_columns[4].metric(
                "Edge",
                f"{latest.edge:.1%}",
            )

            st.plotly_chart(
                px.line(
                    dataframe.tail(1000),
                    x="timestamp",
                    y=["model_p_up", "yes_ask"],
                    title=(
                        "Model probability versus YES ask"
                    ),
                ),
                width="stretch",
            )

            st.dataframe(
                dataframe.tail(200).iloc[::-1],
                width="stretch",
            )
    else:
        st.info("Run the live paper engine first.")