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
    current_market_selection,
    market_summary,
    paper_bankroll_history,
    paper_entry_diagnostics,
    paper_trading_summary,
    signal_calibration_report,
    recent_bars,
    recent_market_selections,
    recent_paper_decisions,
    recent_paper_trades,
    recent_signal_history,
    recent_trades,
)
from kalshi_quant.config import Settings
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

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "Coinbase Market",
        "Backtest",
        "Live Snapshots",
        "Paper Trading",
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
        confirmation_bars = recent_bars(
            product_id=product_id,
            interval_seconds=60,
            limit=max(bar_limit, 100),
        )

        try:
            technical_signal = evaluate_market_signal(
                bars,
                confirmation_bars=(
                    confirmation_bars
                    if interval_seconds != 60
                    else None
                ),
            )
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

        st.subheader("Automatic 5-second signal history")

        signal_history = recent_signal_history(
            product_id=product_id,
            interval_seconds=5,
            limit=200,
        )

        if signal_history.empty:
            st.info(
                "No automatic signals are stored yet. Start the "
                "Coinbase recorder and allow at least 20 completed "
                "5-second bars to accumulate."
            )
        else:
            latest_stored_signal = signal_history.iloc[-1]
            history_kpis = st.columns(4)

            history_kpis[0].metric(
                "Stored signals",
                f"{len(signal_history):,}",
            )
            history_kpis[1].metric(
                "Latest stored score",
                f'{float(latest_stored_signal["score"]):+.1f}',
            )
            history_kpis[2].metric(
                "Latest stored P(up)",
                f'{float(latest_stored_signal["probability_up"]):.1%}',
            )
            history_kpis[3].metric(
                "Latest stored confidence",
                f'{float(latest_stored_signal["confidence"]):.1%}',
            )

            history_left, history_right = st.columns(2)

            score_history_chart = go.Figure()
            score_history_chart.add_trace(
                go.Scatter(
                    x=signal_history["timestamp"],
                    y=signal_history["score"],
                    mode="lines+markers",
                    name="Technical score",
                )
            )
            score_history_chart.add_hline(
                y=25,
                line_dash="dash",
                annotation_text="Long-bias threshold",
            )
            score_history_chart.add_hline(
                y=-25,
                line_dash="dash",
                annotation_text="Short-bias threshold",
            )
            score_history_chart.add_hline(
                y=0,
                line_dash="dot",
            )
            score_history_chart.update_layout(
                title="Stored technical score",
                xaxis_title="Time",
                yaxis_title="Score",
                yaxis={"range": [-100, 100]},
                height=375,
                showlegend=False,
            )
            history_left.plotly_chart(
                score_history_chart,
                width="stretch",
            )

            probability_history_chart = go.Figure()
            probability_history_chart.add_trace(
                go.Scatter(
                    x=signal_history["timestamp"],
                    y=signal_history["probability_up"] * 100,
                    mode="lines",
                    name="Technical P(up)",
                )
            )
            probability_history_chart.add_trace(
                go.Scatter(
                    x=signal_history["timestamp"],
                    y=signal_history["confidence"] * 100,
                    mode="lines",
                    name="Confidence",
                )
            )
            probability_history_chart.update_layout(
                title="Probability and confidence history",
                xaxis_title="Time",
                yaxis_title="Percent",
                yaxis={"range": [0, 100]},
                height=375,
                hovermode="x unified",
            )
            history_right.plotly_chart(
                probability_history_chart,
                width="stretch",
            )

            history_columns = [
                "timestamp",
                "direction",
                "action",
                "score",
                "probability_up",
                "confidence",
                "volatility_regime",
                "order_flow_imbalance",
                "order_flow_reliability",
                "timeframe_confirmation",
                "timeframe_agreement",
            ]

            st.dataframe(
                signal_history[history_columns].iloc[::-1],
                width="stretch",
                hide_index=True,
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

with tab4:
    settings = Settings()
    summary = paper_trading_summary(
        starting_bankroll=settings.paper_bankroll,
    )

    st.subheader("Automatic paper trading and settlement")

    selected_market = current_market_selection()
    selection_history = recent_market_selections(limit=200)

    if not settings.paper_mode:
        st.error(
            "PAPER_MODE is disabled. No simulated entries will be "
            "created until PAPER_MODE=true."
        )
    elif settings.kalshi_auto_discovery:
        if selected_market is None:
            st.info(
                "Automatic Kalshi market discovery is enabled. "
                "Start the recorder to select the first compatible "
                "BTC market."
            )
        else:
            st.success(
                "Simulation only — automatic market discovery is "
                "active. Selected market: "
                f"{selected_market['market_ticker']}"
            )
    elif not settings.kalshi_market_ticker:
        st.info(
            "Paper trading is ready but inactive. Configure "
            "KALSHI_MARKET_TICKER and KALSHI_TARGET_PRICE in .env."
        )
    else:
        st.success(
            "Simulation only — no live-order method is called. "
            f"Configured market: {settings.kalshi_market_ticker}"
        )

    st.subheader("Automatic Kalshi market discovery")

    if settings.kalshi_auto_discovery:
        st.caption(
            f"Primary series: {settings.kalshi_primary_series} · "
            f"Fallback series: {settings.kalshi_fallback_series} · "
            "Only directional BTC contracts with acceptable time, "
            "quotes, spread, price, target distance, and liquidity "
            "are eligible."
        )

        if selected_market is None:
            st.info(
                "No market-selection record is stored yet. The "
                "recorder creates one after its first successful "
                "automatic discovery."
            )
        else:
            discovery_kpis = st.columns(6)
            discovery_kpis[0].metric(
                "Selected market",
                str(selected_market["market_ticker"]),
            )
            discovery_kpis[1].metric(
                "Series",
                str(selected_market["series_ticker"]),
            )
            discovery_kpis[2].metric(
                "Target",
                f"${float(selected_market['target_price']):,.2f}",
            )
            discovery_kpis[3].metric(
                "BTC at selection",
                f"${float(selected_market['btc_price']):,.2f}",
            )
            discovery_kpis[4].metric(
                "Time left at selection",
                f"{float(selected_market['seconds_remaining']):,.0f}s",
            )
            discovery_kpis[5].metric(
                "Spread",
                (
                    f"{float(selected_market['spread']):.2%}"
                    if selected_market.get("spread") is not None
                    else "Unavailable"
                ),
            )

            quote_kpis = st.columns(6)
            quote_kpis[0].metric(
                "YES ask",
                (
                    f"{float(selected_market['yes_ask']):.2%}"
                    if selected_market.get("yes_ask") is not None
                    else "Unavailable"
                ),
            )
            quote_kpis[1].metric(
                "NO ask",
                (
                    f"{float(selected_market['no_ask']):.2%}"
                    if selected_market.get("no_ask") is not None
                    else "Unavailable"
                ),
            )
            quote_kpis[2].metric(
                "Volume",
                f"{float(selected_market['volume']):,.0f}",
            )
            quote_kpis[3].metric(
                "Open interest",
                f"{float(selected_market['open_interest']):,.0f}",
            )
            quote_kpis[4].metric(
                "Selection type",
                (
                    "Rollover"
                    if int(selected_market.get("rollover") or 0)
                    else "Initial"
                ),
            )
            quote_kpis[5].metric(
                "Previous market",
                str(
                    selected_market.get("previous_ticker")
                    or "None"
                ),
            )

            st.caption(
                "Selection reason: "
                f"{selected_market['selection_reason']}"
            )

        if not selection_history.empty:
            discovery_chart = px.scatter(
                selection_history.sort_values("selected_at"),
                x="selected_at",
                y="target_price",
                color="series_ticker",
                symbol="rollover",
                hover_data=[
                    "market_ticker",
                    "btc_price",
                    "seconds_remaining",
                    "yes_ask",
                    "no_ask",
                    "spread",
                    "volume",
                    "open_interest",
                    "selection_reason",
                    "previous_ticker",
                ],
                title="Automatic market selections and rollovers",
            )
            st.plotly_chart(
                discovery_chart,
                width="stretch",
            )

            st.dataframe(
                selection_history,
                width="stretch",
                hide_index=True,
            )
    else:
        st.info(
            "Automatic discovery is disabled. The paper engine uses "
            "the manually configured KALSHI_MARKET_TICKER."
        )

    top_kpis = st.columns(6)
    top_kpis[0].metric(
        "Current bankroll",
        f"${summary['current_bankroll']:,.2f}",
        delta=f"${summary['realized_pnl']:+,.2f}",
    )
    top_kpis[1].metric(
        "Realized P&L",
        f"${summary['realized_pnl']:+,.2f}",
    )
    top_kpis[2].metric(
        "ROI",
        f"{summary['roi']:.2%}",
    )
    top_kpis[3].metric(
        "Closed trades",
        f"{summary['closed_trades']:,}",
    )
    top_kpis[4].metric(
        "Win rate",
        f"{summary['win_rate']:.1%}",
    )
    top_kpis[5].metric(
        "Max drawdown",
        f"{summary['max_drawdown']:.2%}",
    )

    secondary_kpis = st.columns(6)
    secondary_kpis[0].metric(
        "Decisions",
        f"{summary['total_decisions']:,}",
    )
    secondary_kpis[1].metric(
        "Simulated trades",
        f"{summary['total_trades']:,}",
    )
    secondary_kpis[2].metric(
        "Open trades",
        f"{summary['open_trades']:,}",
    )
    secondary_kpis[3].metric(
        "Wins / losses",
        f"{summary['wins']:,} / {summary['losses']:,}",
    )
    secondary_kpis[4].metric(
        "Active stake",
        f"${summary['active_stake']:,.2f}",
    )
    secondary_kpis[5].metric(
        "Average P&L",
        f"${summary['average_pnl']:+,.2f}",
    )

    st.caption(
        "Entries must pass technical direction, confidence, Kalshi "
        "edge, spread, time-window, daily-loss, and Kelly-size checks. "
        "Open trades close only after a final YES or NO market result."
    )

    calibration = signal_calibration_report(
        product_id="BTC-USD",
        interval_seconds=5,
        episode_gap_seconds=15.0,
    )

    calibration_summary = calibration["summary"]
    calibration_actions = calibration["action_counts"]
    calibration_scenarios = calibration["threshold_scenarios"]
    calibration_buckets = calibration["score_buckets"]

    st.subheader("Signal calibration report")

    total_calibration_signals = int(
        calibration_summary["total_signals"]
    )

    if total_calibration_signals == 0:
        st.info(
            "No stored technical signals are available for "
            "calibration reporting."
        )
    else:
        current_scenario_rows = calibration_scenarios[
            (
                calibration_scenarios["score_threshold"]
                .sub(25.0)
                .abs()
                < 1e-9
            )
            & (
                calibration_scenarios["confidence_threshold"]
                .sub(0.25)
                .abs()
                < 1e-9
            )
        ]

        current_scenario = (
            current_scenario_rows.iloc[0]
            if not current_scenario_rows.empty
            else None
        )

        calibration_kpis = st.columns(6)

        calibration_kpis[0].metric(
            "Signals analyzed",
            f"{total_calibration_signals:,}",
        )
        calibration_kpis[1].metric(
            "LONG bias",
            f"{int(calibration_summary['long_bias_count']):,}",
        )
        calibration_kpis[2].metric(
            "SHORT bias",
            f"{int(calibration_summary['short_bias_count']):,}",
        )

        if current_scenario is None:
            calibration_kpis[3].metric(
                "Candidate signals",
                "N/A",
            )
            calibration_kpis[4].metric(
                "Candidate episodes",
                "N/A",
            )
            calibration_kpis[5].metric(
                "Signals per episode",
                "N/A",
            )
        else:
            calibration_kpis[3].metric(
                "Candidate signals",
                f"{int(current_scenario['candidate_count']):,}",
            )
            calibration_kpis[4].metric(
                "Candidate episodes",
                (
                    f"{int(current_scenario['candidate_episode_count']):,}"
                ),
            )
            calibration_kpis[5].metric(
                "Signals per episode",
                (
                    f"{float(current_scenario['average_signals_per_episode']):.1f}"
                ),
            )

        st.caption(
            "Candidate episodes combine consecutive signals in the "
            "same direction when the gap is no greater than "
            f"{calibration_summary['episode_gap_seconds']:.0f} seconds. "
            "The current comparison uses score ±25 and confidence 25%."
        )

        calibration_chart_columns = st.columns(2)

        action_chart = px.bar(
            calibration_actions,
            x="action",
            y="count",
            text="count",
            hover_data=["rate"],
            labels={
                "action": "Technical action",
                "count": "Signals",
                "rate": "Share",
            },
            title="Stored technical-action distribution",
        )

        action_chart.update_traces(
            textposition="outside",
        )

        calibration_chart_columns[0].plotly_chart(
            action_chart,
            width="stretch",
        )

        score_bucket_chart = px.bar(
            calibration_buckets,
            x="score_bucket",
            y="count",
            text="count",
            hover_data=["rate"],
            labels={
                "score_bucket": "Absolute score range",
                "count": "Signals",
                "rate": "Share",
            },
            title="Absolute technical-score distribution",
        )

        score_bucket_chart.update_traces(
            textposition="outside",
        )

        calibration_chart_columns[1].plotly_chart(
            score_bucket_chart,
            width="stretch",
        )

        scenario_display = calibration_scenarios.copy()
        scenario_display["confidence_threshold_percent"] = (
            scenario_display["confidence_threshold"] * 100.0
        )
        scenario_display["candidate_rate_percent"] = (
            scenario_display["candidate_rate"] * 100.0
        )

        st.dataframe(
            scenario_display[
                [
                    "score_threshold",
                    "confidence_threshold_percent",
                    "candidate_count",
                    "candidate_episode_count",
                    "long_episodes",
                    "short_episodes",
                    "average_signals_per_episode",
                    "candidate_rate_percent",
                ]
            ],
            width="stretch",
            hide_index=True,
            column_config={
                "score_threshold": st.column_config.NumberColumn(
                    "Score threshold",
                    format="%.0f",
                ),
                "confidence_threshold_percent": (
                    st.column_config.NumberColumn(
                        "Confidence threshold",
                        format="%.0f%%",
                    )
                ),
                "candidate_count": "Candidate signals",
                "candidate_episode_count": "Candidate episodes",
                "long_episodes": "LONG episodes",
                "short_episodes": "SHORT episodes",
                "average_signals_per_episode": (
                    st.column_config.NumberColumn(
                        "Signals per episode",
                        format="%.1f",
                    )
                ),
                "candidate_rate_percent": (
                    st.column_config.NumberColumn(
                        "Candidate rate",
                        format="%.1f%%",
                    )
                ),
            },
        )

    history = paper_bankroll_history(limit=1000)

    st.subheader("Bankroll and drawdown")

    if history.empty:
        st.info(
            "No settled paper trades are available for the "
            "performance charts yet."
        )
    else:
        equity_chart = px.line(
            history,
            x="settled_at",
            y=["bankroll_after", "peak_bankroll"],
            markers=True,
            title="Paper bankroll and running peak",
        )
        st.plotly_chart(
            equity_chart,
            width="stretch",
        )

        pnl_chart = px.bar(
            history,
            x="settled_at",
            y="pnl",
            hover_data=[
                "market_ticker",
                "side",
                "market_result",
                "contracts",
                "stake",
                "bankroll_after",
                "drawdown",
            ],
            title="Realized P&L by settled paper trade",
        )
        st.plotly_chart(
            pnl_chart,
            width="stretch",
        )

    diagnostics = paper_entry_diagnostics(
        min_confidence=settings.paper_min_confidence,
        max_spread=settings.paper_max_spread,
        min_seconds=settings.paper_min_seconds,
        max_seconds=settings.paper_max_seconds,
        min_edge=settings.min_edge,
    )

    st.subheader("Paper entry-gate diagnostics")

    total_diagnostic_decisions = (
        int(diagnostics["total_decisions"].max())
        if not diagnostics.empty
        else 0
    )

    if total_diagnostic_decisions == 0:
        st.info(
            "No paper decisions are available for gate diagnostics."
        )
    else:
        diagnostics_display = diagnostics.copy()
        diagnostics_display["pass_rate_percent"] = (
            diagnostics_display["pass_rate"] * 100.0
        )

        failed_rows = diagnostics_display[
            diagnostics_display["failed"] > 0
        ]

        if failed_rows.empty:
            top_blocking_gate = "None"
            top_blocking_count = 0
        else:
            top_blocking_row = failed_rows.loc[
                failed_rows["failed"].idxmax()
            ]
            top_blocking_gate = str(top_blocking_row["gate"])
            top_blocking_count = int(top_blocking_row["failed"])

        risk_row = diagnostics_display[
            diagnostics_display["gate"] == "Risk controls"
        ].iloc[0]

        diagnostic_kpis = st.columns(4)

        diagnostic_kpis[0].metric(
            "Decisions analyzed",
            f"{total_diagnostic_decisions:,}",
        )
        diagnostic_kpis[1].metric(
            "Reached risk controls",
            f"{int(risk_row['evaluated']):,}",
        )
        diagnostic_kpis[2].metric(
            "Passed all gates",
            f"{int(risk_row['passed']):,}",
        )
        diagnostic_kpis[3].metric(
            "Largest blocking gate",
            top_blocking_gate,
            delta=f"{top_blocking_count:,} failed",
            delta_color="off",
        )

        gate_chart = px.bar(
            diagnostics_display,
            x="gate",
            y=["passed", "failed"],
            barmode="group",
            hover_data=[
                "threshold",
                "evaluated",
                "not_evaluated",
                "pass_rate_percent",
            ],
            labels={
                "value": "Decision count",
                "variable": "Result",
                "gate": "Entry gate",
                "pass_rate_percent": "Pass rate (%)",
            },
            title="Sequential paper-entry gate results",
        )

        st.plotly_chart(
            gate_chart,
            width="stretch",
        )

        st.dataframe(
            diagnostics_display[
                [
                    "gate",
                    "threshold",
                    "evaluated",
                    "passed",
                    "failed",
                    "not_evaluated",
                    "pass_rate_percent",
                ]
            ],
            width="stretch",
            hide_index=True,
            column_config={
                "gate": "Entry gate",
                "threshold": "Required condition",
                "evaluated": "Evaluated",
                "passed": "Passed",
                "failed": "Failed",
                "not_evaluated": "Not reached",
                "pass_rate_percent": st.column_config.NumberColumn(
                    "Pass rate",
                    format="%.1f%%",
                ),
            },
        )

    decisions = recent_paper_decisions(limit=200)

    st.subheader("Recent paper decisions")

    if decisions.empty:
        st.info("No paper decisions have been stored yet.")
    else:
        decision_chart = px.scatter(
            decisions.sort_values("signal_timestamp"),
            x="signal_timestamp",
            y="technical_score",
            color="decision",
            hover_data=[
                "market_ticker",
                "side",
                "edge",
                "contracts",
                "stake",
                "reason",
            ],
            title="Technical score and paper decisions",
        )

        decision_chart.add_hline(
            y=25,
            line_dash="dash",
        )
        decision_chart.add_hline(
            y=-25,
            line_dash="dash",
        )

        st.plotly_chart(
            decision_chart,
            width="stretch",
        )

        st.dataframe(
            decisions,
            width="stretch",
            hide_index=True,
        )

    trades = recent_paper_trades(limit=200)

    st.subheader("Simulated paper trades")

    if trades.empty:
        st.info("No simulated paper trades have been opened.")
    else:
        st.dataframe(
            trades,
            width="stretch",
            hide_index=True,
        )

