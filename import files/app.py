"""
Stock Analysis – Streamlit app.
Run from terminal:  streamlit run app.py
"""
import os
from pathlib import Path

import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")
from utils import (
    get_fx_rate,
    get_price_local,
    get_prices_batch,
    get_prices_via_chart_api,
    _yahoo_session,
    compute_moving_averages,
    plot_moving_averages,
    get_history,
    latest_vs_ma_label,
    compute_volatility,
    compute_volatility_from_price_history,
    plot_volatility,
    plot_pe_ratio,
    compute_pe_ratio,
    beta_values,
    plot_beta,
    compute_sharpe_ratio,
    compute_rsi,
    compute_macd,
    compute_macd_cmf_ema_supertrend,
    plot_macd_cmf_ema_supertrend,
    build_tradesmart_paper_trades,
    get_alpaca_trading_client,
    execute_tradesmart_signal_on_alpaca,
    format_new_instrument_assessment,
    build_portfolio_kpi_dataframe,
    generate_portfolio_ai_markdown,
    format_overall_portfolio_note_heuristic,
)

# Common Yahoo symbol aliases for the Investment Possibilities tab
_IDEA_TICKER_ALIASES = {"ORACLE": "ORCL"}

st.set_page_config(page_title="Stock Analysis", page_icon=":chart_with_upwards_trend:")
st.title("📊 Financial Performance Analysis")
st.markdown("🧾 Upload a CSV of your holdings to view gains and prices, plus recommendations 🤖")
st.markdown("## 📁 Upload your CSV file")
uploaded_file = st.file_uploader("📂 Upload your CSV file", type=["csv"])


if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False
if "flag" not in st.session_state:
    st.session_state.flag = False
if "vol_flag" not in st.session_state:
    st.session_state.vol_flag = False
if "pe_flag" not in st.session_state:
    st.session_state.pe_flag = False
if "sharpe_flag" not in st.session_state:
    st.session_state.sharpe_flag = False
if "rsi_flag" not in st.session_state:
    st.session_state.rsi_flag = False
if "macd_flag" not in st.session_state:
    st.session_state.macd_flag = False
if "tradesmart_flag" not in st.session_state:
    st.session_state.tradesmart_flag = False
if "idea_tickers" not in st.session_state:
    st.session_state.idea_tickers = []
# Default idea tickers (course: portfolio & new instruments) — once per session.
if "idea_default_tickers_v2" not in st.session_state:
    st.session_state.idea_default_tickers_v2 = True
    for _sym in ("SXR8.DE", "NVDA"):
        if _sym not in st.session_state.idea_tickers:
            st.session_state.idea_tickers.append(_sym)

if uploaded_file is not None and not st.session_state.data_loaded:
    import pandas as pd
    raw = pd.read_csv(uploaded_file)
    raw.columns = raw.columns.str.strip()
    st.session_state.df = raw
    st.session_state.data_loaded = True

# Required CSV columns (names after stripping whitespace)
REQUIRED_COLUMNS = ["Asset", "Ticker", "Currency Yahoo", "Units", "Purchase Price", "Value Last Update"]

# Start the analysis (all heavy imports here so first paint is instant)
if st.session_state.data_loaded:
    import pandas as pd
    import numpy as np
    from datetime import datetime
    from utils import get_fx_rate, get_price_local, get_prices_batch, get_prices_via_chart_api, _yahoo_session
    import yfinance as yf

    df = st.session_state.df.copy()
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        st.error(f"⚠️ CSV is missing required columns: **{', '.join(missing)}**. Expected: {', '.join(REQUIRED_COLUMNS)}")
        st.code("Asset, Ticker, Currency Yahoo, Units, Purchase Price, Value Last Update", language="text")
    else:
        # Create the tabs
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
            [
                "💹 Gains",
                "🔄 Stock updates",
                "📥 Export data",
                "📉 Stock analysis",
                "✨ AI Recommendations",
                "➕ Investment Possibilities",
            ]
        )
        with tab1:
            for col in ["Units", "Purchase Price", "Value Last Update"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

            # Only fetch prices when user clicks — keeps page load instant, no white screen
            if "load_prices" not in st.session_state:
                st.session_state.load_prices = False
            if st.button("Load current prices 🔎", key="btn_load_prices"):
                st.session_state.load_prices = True

            if st.session_state.load_prices:
                with st.spinner("⏳ Loading prices…"):
                    try:
                        session = _yahoo_session()
                        fx_cache = {}
                        for fx in df["Currency Yahoo"].dropna().unique():
                            fx_cache[fx] = 1.0 if fx == "EUR" else get_fx_rate(fx, session=session)
                        tickers_uniq = df["Ticker"].astype(str).str.strip().unique().tolist()
                        prices_native = get_prices_batch(tickers_uniq, session=session)
                        if not prices_native:
                            prices_native = get_prices_via_chart_api(tickers_uniq, session=session)

                        def _price_eur(row):
                            t = str(row["Ticker"]).strip()
                            native = prices_native.get(t, np.nan)
                            if pd.isna(native) or native <= 0:
                                return get_price_local(row, fx_cache, session=session)
                            rate = fx_cache.get(row["Currency Yahoo"], np.nan)
                            return np.nan if (pd.isna(rate) or rate <= 0) else native * rate

                        df["Price Today (EUR)"] = df.apply(_price_eur, axis=1)
                    except Exception as e:
                        df["Price Today (EUR)"] = np.nan
                        st.warning(f"⚠️ Could not load prices: {e}")
            else:
                df["Price Today (EUR)"] = np.nan
                st.info("👉 Click **Load current prices 🔎** to refresh prices.")

            # Value and gains (all in EUR for consistency)
            # Value Today = current price × units held
            df["Value Today (EUR)"] = df["Price Today (EUR)"] * df["Units"]
            # Gain since Last Update = value now minus value at last update
            df["Gain since Last Update (EUR)"] = df["Value Today (EUR)"] - df["Value Last Update"]
            # Cost basis = units × average purchase price; gain = value now minus cost basis
            cost_basis = df["Units"] * df["Purchase Price"]
            df["Gain since Purchase (EUR)"] = df["Value Today (EUR)"] - cost_basis
            # Percent gains (avoid division by zero)
            value_last = df["Value Last Update"].replace(0, np.nan)
            cost_basis_safe = cost_basis.replace(0, np.nan)
            df["Gain since Last Update (%)"] = (df["Gain since Last Update (EUR)"] / value_last * 100).replace([np.inf, -np.inf], np.nan)
            df["Gain since Purchase (%)"] = (df["Gain since Purchase (EUR)"] / cost_basis_safe * 100).replace([np.inf, -np.inf], np.nan)

            if df["Price Today (EUR)"].isna().all():
                tickers_in_file = ", ".join(df["Ticker"].astype(str).str.strip().unique().tolist())
                st.warning(
                    "⚠️ Could not fetch current prices for any ticker. Your CSV uses: **" + tickers_in_file + "**. "
                    "Each **Ticker** must be a Yahoo Finance symbol (e.g. AAPL, MSFT, GOOGL, BTC-EUR, ETH-USD). "
                    "Look up symbols at [finance.yahoo.com](https://finance.yahoo.com/lookup)."
                )
            elif df["Price Today (EUR)"].isna().any():
                failed = df.loc[df["Price Today (EUR)"].isna(), "Ticker"].unique().tolist()
                st.info("ℹ️ No price found for: **" + ", ".join(str(t) for t in failed) + "**. Other tickers loaded.")

            # Totals row: sum EUR gains; total % = portfolio return (total gain / total cost), not sum of %
            total_cost = cost_basis.sum()
            total_gain_last = df["Gain since Last Update (EUR)"].sum()
            total_gain_purchase = df["Gain since Purchase (EUR)"].sum()
            total_gain_pct = (total_gain_purchase / total_cost * 100) if total_cost and abs(total_cost) > 1e-9 else 0.0
            totals = {
                "Asset": "Total",
                "Ticker": "",
                "Gain since Last Update (EUR)": float(total_gain_last),
                "Gain since Purchase (EUR)": float(total_gain_purchase),
                "Gain since Purchase (%)": float(total_gain_pct),
            }

            gain_cols = ["Gain since Last Update (EUR)", "Gain since Purchase (EUR)", "Gain since Purchase (%)"]
            columns = ["Asset", "Ticker"] + gain_cols
            report = pd.concat([df[columns], pd.DataFrame([totals])], ignore_index=True)


            

            def _color_gains(val):
                if pd.isna(val):
                    return ""
                try:
                    v = float(val)
                    if v > 0:
                        return "color: #0d7a0d; font-weight: bold;"  # green
                    if v < 0:
                        return "color: #c00; font-weight: bold;"      # red
                except (TypeError, ValueError):
                    pass
                return ""

            styled = (
                report.style.format("{:,.2f}", subset=gain_cols, na_rep="—")
                .apply(lambda s: [_color_gains(v) for v in s], subset=gain_cols)
            )
            today = datetime.now().strftime("%Y-%m-%d")
            st.markdown(f"### 📈 Snapshot of financial performance — {today}")
            st.dataframe(styled, use_container_width=True)
            st.caption("💡 Gain since Last Update = value today vs value at last update. Gain since Purchase = value today vs cost (Units × Purchase Price).")

            # Keep session copy in sync with computed columns (Price Today, gains, etc.) for Export tab
            st.session_state.df = df.copy()

            ### Tab2 
        with tab2:
            # Ask if there is any update
            update = st.radio("📝 Any updates to your portfolio?", ["Yes", "No"], horizontal=True)
            if update == "Yes":
                st.markdown("## 📝 Stock Asset Details")
                selected_asset = st.selectbox("🎯 Select an asset", st.session_state.df["Asset"].unique().tolist())
                
                # Ask for the units and price
                changed_units = st.number_input(
                    "🔢 Units bought (+) or sold (−), e.g. 2 or −2:",
                    value=0.0,
                    step=0.01,
                    format="%.2f",
                    help="➕ Positive = bought · ➖ Negative = sold",
                )
                new_purchase_price = st.number_input(
                    "💶 Purchase price per unit (EUR):",
                    min_value=0.0,
                    value=0.0,
                    step=0.01,
                    format="%.2f",
                )    
                
                if st.button("💾 Update asset"):
                    if selected_asset and changed_units != 0 and new_purchase_price > 0:
                        # Update units and average purchase price
                        idx = st.session_state.df[st.session_state.df["Asset"] == selected_asset].index[0]
                        old_units = st.session_state.df.at[idx, "Units"]
                        st.session_state.df.at[idx, "Units"] = old_units + changed_units

                        # Update the average purchase price
                        old_purchase_price = st.session_state.df.at[idx, "Purchase Price"]
                        st.session_state.df.at[idx, "Purchase Price"] = (old_purchase_price * old_units + changed_units * new_purchase_price) / (old_units + changed_units)

                        st.success(
                            f"✅ Updated **{selected_asset}** — {old_units + changed_units} units @ "
                            f"{st.session_state.df.at[idx, 'Purchase Price']}"
                        )

                    else:
                        st.error("📝 Please fill in all fields and select an asset to update.")
            # Add new assets to the portfolio
            new_asset = st.radio("➕ Add a brand-new holding?", ["Yes", "No"], horizontal=True)
            if new_asset == "Yes":
                st.markdown("## 📝 New Asset Details")
                asset_name = st.text_input("🏷️ Asset name")
                ticker = st.text_input("🔤 Yahoo ticker (e.g. AAPL)")
                currency = st.selectbox("💱 Currency (Yahoo)", ["EUR", "USD", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY", "SEK", "NZD"], index=0)
                units = st.number_input("🔢 Units", min_value=0.000001, step=0.000001)
                purchase_price = st.number_input("💶 Purchase price (per unit)", min_value=0.0, step=0.000001)

                if st.button("➕ Add asset"):
                    if asset_name and ticker and currency and units > 0 and purchase_price > 0:
                        stock = yf.Ticker(ticker)
                        info = stock.info
                        if "shortName" in info:
                            new_row = {
                                "Asset": asset_name,
                                "Ticker": ticker,
                                "Currency Yahoo": currency,
                                "Units": units,
                                "Purchase Price": purchase_price,
                                "Currency Purchase": "EUR",
                                "Price Last Update": np.nan,
                                "Date Last Update": np.nan,
                                "Value Last Update": np.nan,
                                "Profit Last Update": np.nan
                            }
                            st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame([new_row])], ignore_index=True)
                            st.success(f"➕ Added '{asset_name}' to portfolio.")
                        else:
                            st.error("🔍 Ticker not found — check the symbol on Yahoo Finance.")
                    else:
                        st.error("📝 Please fill in every field with valid numbers before adding.")

        with tab3:
            st.markdown("### 📥 Export Data")
            # Show selected data
            selected_data = st.session_state.df.iloc[:, :10]
            st.dataframe(selected_data, use_container_width=True)
            # Download the selected data
            today_export = datetime.now().strftime("%Y-%m-%d")
            export_df = st.session_state.df.copy()
            if "Price Today (EUR)" in export_df.columns:
                export_df["Price Last Update"] = export_df["Price Today (EUR)"]
            export_df["Date Last Update"] = today_export
            n_cols = min(10, export_df.shape[1])
            csv_bytes = export_df.iloc[:, :n_cols].to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Download CSV",
                data=csv_bytes,
                file_name=f"assets_{today_export}.csv",
                mime="text/csv",
            )
            st.caption("💡 Export uses the first 10 columns of your portfolio table (including latest prices if loaded).")

        with tab4:
            st.markdown("### 📉 Stock analysis")
            subtab1, subtab2, subtab3, subtab4, subtab5, subtab6, subtab7, subtab8 = st.tabs(
                [
                    "Moving Average",
                    "Volatility",
                    "P/E Ratio",
                    "Beta",
                    "Sharpe Ratio",
                    "RSI",
                    "MACD",
                    "MACD+CMF+EMA+Supertrend",
                ]
            )
            with subtab1:
                if st.button("📊 Analyze holdings", key="btn_stock_analyze"):
                    st.session_state.flag = True
                st.markdown(
                    """
#### 📈 Moving averages — how to read the chart

- **What this tab does:** For each holding it loads **daily closing prices** (~1 year), computes **MA50, MA100, and MA200**, plots them against price, and shows whether the latest close is **above or below** each average.
- **MA50 (short-term):** Tracks the last ~50 trading days. It reacts quickly; use it for near-term trend and support/resistance.
- **MA100 (medium-term):** Smoother than the 50; helps filter noise and see the intermediate trend.
- **MA200 (long-term):** A common benchmark for the broader trend. Price staying above it is often read as strength; sustained time below as weakness.

**📍 When averages cross each other**

- **Shorter MA crosses above a longer MA** (e.g. 50 above 100 or 200): Often interpreted as a **bullish** shift—recent prices are outperforming the longer average (sometimes called a “golden cross” ✨ when 50 crosses above 200).
- **Shorter MA crosses below a longer MA**: Often interpreted as a **bearish** shift—momentum is weakening vs. the longer trend (sometimes called a “death cross” ⚡ for 50 below 200).
- **Lines bunch together:** Usually means a **range or consolidation** ↔️—trend signals are weaker until price breaks with the MAs fanning out again.

*⏪ Moving averages are backward-looking; crosses can lag real turns and work better as context than as standalone buy/sell rules.*
"""
                )
                if not st.session_state.flag:
                    st.info("📌 Click **📊 Analyze holdings** above to load charts for each ticker.")
                else:
                    for ticker in st.session_state.df["Ticker"].astype(str).str.strip().unique():
                        price_history, latest = compute_moving_averages(ticker)
                        if price_history is None:
                            st.warning(f"📡 Could not load historical data for **{ticker}**.")
                            continue
                        st.markdown(f"##### {ticker} 📊")
                        fig = plot_moving_averages(price_history, ticker)
                        if fig is not None:
                            st.pyplot(fig, use_container_width=True)
                        if latest is not None:
                            lp = latest["latest_price"]
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("Spot 💹", f"{lp:.2f}" if pd.notna(lp) else "—")
                            c2.metric("MA50", f"{latest['ma50']:.2f}" if pd.notna(latest["ma50"]) else "—")
                            c3.metric("MA100", f"{latest['ma100']:.2f}" if pd.notna(latest["ma100"]) else "—")
                            c4.metric("MA200", f"{latest['ma200']:.2f}" if pd.notna(latest["ma200"]) else "—")
                            tag_icon = {"Above": "📈", "Below": "📉", "Equal": "⚖️", "n/a": "❔"}
                            rows = []
                            for label, key in (("MA50", "ma50"), ("MA100", "ma100"), ("MA200", "ma200")):
                                ma = latest[key]
                                tag = latest_vs_ma_label(lp, ma)
                                val = f"{ma:.2f}" if pd.notna(ma) else "—"
                                icon = tag_icon.get(tag, "")
                                rows.append(f"- **{label}:** {val} — spot vs MA: **{tag}** {icon}")
                            st.markdown("\n".join(rows))
            with subtab2:
                st.markdown("##### Key points")
                st.markdown(
                    """
- **Volatility** measures how much a stock’s price fluctuates. 📈
- **Higher volatility** = higher risk and potential reward. ⚡
- **Lower volatility** = more stable, less dramatic moves. 🛡️
- **Compare volatility** across stocks to assess risk. 🔍
- Use **rolling volatility** to spot changes in market behavior. 🔄
- **What this tab does:** After you click the button, it uses each ticker’s **daily returns** to compute **annualized rolling volatility (%)** (latest value per name), shows a **portfolio bar chart**, and optional **per-ticker time series** in the expander.
"""
                )
                if st.button("📊 Show portfolio volatility", key="btn_vol_analyze"):
                    st.session_state.vol_flag = True
                if not st.session_state.vol_flag:
                    st.caption("Click **Show portfolio volatility** to load latest vol per ticker and the comparison chart.")
                else:
                    vol_summary = {}
                    for ticker in st.session_state.df["Ticker"].astype(str).str.strip().unique():
                        price_history, _ = get_history(ticker)
                        if price_history is None or price_history.empty:
                            continue
                        v = compute_volatility_from_price_history(price_history)
                        if v is not None:
                            vol_summary[ticker] = v
                    if vol_summary:
                        st.markdown("##### Latest volatility by ticker")
                        for t, v in vol_summary.items():
                            st.markdown(
                                f"- **Ticker:** {t} — **Latest volatility:** **{v:.1f}%** 📉"
                            )
                        st.markdown("---")
                        fig_vol, ax_v = plt.subplots(figsize=(10, 5))
                        tickers_ord = list(vol_summary.keys())
                        vals = [vol_summary[t] for t in tickers_ord]
                        x = np.arange(len(tickers_ord))
                        ax_v.bar(x, vals, color="#7EC8E3", edgecolor="white", linewidth=0.5)
                        ax_v.set_xticks(x)
                        ax_v.set_xticklabels(tickers_ord, rotation=45, ha="right")
                        ax_v.set_title("Portfolio Tickers Volatility")
                        ax_v.set_xlabel("Ticker")
                        ax_v.set_ylabel("Volatility (%)")
                        ymax = max(vals) * 1.12 if vals else 40.0
                        ax_v.set_ylim(0, max(ymax, 5.0))
                        ax_v.grid(axis="y", color="#d0d0d0", linestyle="-", linewidth=0.8, alpha=0.9)
                        ax_v.set_axisbelow(True)
                        fig_vol.tight_layout()
                        st.pyplot(fig_vol, use_container_width=True)
                        with st.expander("📈 Per-ticker rolling volatility (time series)"):
                            for ticker in tickers_ord:
                                ph, _ = get_history(ticker)
                                if ph is None or ph.empty:
                                    continue
                                st.markdown(f"**{ticker}**")
                                fig_t = plot_volatility(ph, ticker)
                                if fig_t is not None:
                                    st.pyplot(fig_t, use_container_width=True)
                    else:
                        st.warning("📡 Could not compute volatility for any ticker. Check tickers and try again.")
            with subtab3:
                st.markdown("##### P/E Ratio")
                st.markdown("**Key Points about the P/E Ratio**")
                if st.button("📊 Show portfolio P/E ratios", key="btn_pe_analyze"):
                    st.session_state.pe_flag = True
                if not st.session_state.pe_flag:
                    st.caption(
                        "Click **Show portfolio P/E ratios** to load trailing Yahoo P/E values and draw the portfolio chart."
                    )
                else:
                    with st.spinner("⏳ Loading P/E ratios…"):
                        fig_pe, pe_summary, pe_missing = plot_pe_ratio(st.session_state.df)
                    for t in pe_missing:
                        st.markdown(
                            f"⚠️ Warning: the ticker **{t}** has no P/E Ratio (negative earnings, ETF or Crypto)"
                        )
                    if pe_summary:
                        st.markdown("##### Latest P/E by ticker")
                        for t, pe in pe_summary.items():
                            st.markdown(f"- **Ticker:** {t} — **P/E:** **{pe:.1f}**")
                        st.markdown("---")
                    if fig_pe is not None:
                        st.pyplot(fig_pe, use_container_width=True)
                    elif pe_missing:
                        st.warning(
                            "Could not draw a P/E chart — no tickers had a positive **trailing** P/E with **positive TTM EPS**."
                        )
                    else:
                        st.warning("No tickers found in the portfolio to analyze.")
            with subtab4:
                st.markdown("##### Beta")
                st.markdown("##### Key points")
                st.markdown(
                    """
- **Beta** summarizes how sensitive a stock has been **vs. the overall market** (often anchored near **1** for large US names vs. a broad US index).
- **Beta above ~1** often means **larger swings** than the market on average; **below ~1** often means **smaller swings** (still not guaranteed in every period).
- **Not a full risk picture:** It ignores company-specific news, liquidity, and non-market risks. **ETFs, funds, and international listings** can have betas that are harder to interpret.
- **What this tab does:** Reads **beta** from Yahoo’s `info` for each portfolio ticker and shows a **side-by-side bar chart** so you can compare market sensitivity across holdings.
"""
                )
                betas = {}
                for ticker in st.session_state.df["Ticker"].astype(str).str.strip().unique():
                    beta = beta_values(ticker)
                    if pd.notna(beta):
                        betas[ticker] = beta

                if betas:
                    st.markdown("##### Latest beta by ticker")
                    for ticker, beta in betas.items():
                        st.markdown(f"- **Ticker:** {ticker} — **Beta:** **{beta:.2f}**")
                    st.markdown("---")
                    fig_beta = plot_beta(betas)
                    if fig_beta is not None:
                        st.pyplot(fig_beta, use_container_width=True)
                else:
                    st.warning("No beta values were available for the current portfolio tickers.")
            with subtab5:
                st.markdown("##### Sharpe Ratio")
                st.markdown("##### Key points")
                st.markdown(
                    """
- **Sharpe ratio** compares **excess return** (return above a **risk-free rate**) to **volatility**. Higher values often mean **more return per unit of risk**, over the window you measure.
- **This app:** Uses **daily returns** from ~1 year of history, assumes **risk-free rate ≈ 0** unless you change the code, and **annualizes** with √250 trading days.
- **Caveats:** Very sensitive to the **time window**; a bad month can dominate. Compare Sharpe **across similar periods** and asset types, not as a single “score” forever.
- **What this tab does:** Computes an **annualized Sharpe** per ticker, lists the values, and plots a **portfolio bar chart** (green if ≥ 0, red if negative).
"""
                )
                if st.button("📊 Show portfolio Sharpe ratios", key="btn_sharpe_analyze"):
                    st.session_state.sharpe_flag = True
                if not st.session_state.sharpe_flag:
                    st.caption("Click to compute annualized Sharpe ratio per ticker.")
                else:
                    sharpe_summary = {}
                    for ticker in st.session_state.df["Ticker"].astype(str).str.strip().unique():
                        s = compute_sharpe_ratio(ticker)
                        if s is not None:
                            sharpe_summary[ticker] = s
                    if sharpe_summary:
                        st.markdown("##### Latest Sharpe ratio by ticker")
                        for t, s in sharpe_summary.items():
                            st.markdown(f"- **Ticker:** {t} — **Sharpe:** **{s:.2f}**")
                        st.markdown("---")
                        fig_sh, ax_s = plt.subplots(figsize=(10, 5))
                        tks = list(sharpe_summary.keys())
                        vals = [sharpe_summary[t] for t in tks]
                        x = np.arange(len(tks))
                        colors = ["#2ECC71" if v >= 0 else "#E74C3C" for v in vals]
                        ax_s.bar(x, vals, color=colors, edgecolor="white", linewidth=0.5)
                        ax_s.axhline(0, color="#666666", linewidth=1)
                        ax_s.set_xticks(x)
                        ax_s.set_xticklabels(tks, rotation=45, ha="right")
                        ax_s.set_title("Portfolio Tickers Sharpe Ratio")
                        ax_s.set_xlabel("Ticker")
                        ax_s.set_ylabel("Sharpe Ratio")
                        ax_s.grid(axis="y", color="#d0d0d0", linestyle="-", linewidth=0.8, alpha=0.9)
                        ax_s.set_axisbelow(True)
                        fig_sh.tight_layout()
                        st.pyplot(fig_sh, use_container_width=True)
                    else:
                        st.warning("Could not compute Sharpe ratio for any ticker.")
            with subtab6:
                st.markdown("##### RSI")
                st.markdown("##### Key points")
                st.markdown(
                    """
- **RSI (Relative Strength Index)** is a **momentum oscillator** from 0–100 based on recent gains vs. losses in price (here: **14-day** smoothing).
- **High RSI (often near 70+)** can mean **strong recent buying**; some traders treat that zone as **“overbought”** (not automatic sell—trends can stay stretched).
- **Low RSI (often near 30−)** can mean **weak recent price action**; some treat it as **“oversold”** (not automatic buy—falling stocks can stay oversold).
- **What this tab does:** Computes **RSI over time** for each ticker, shows the **latest RSI** in a list, and plots **full RSI charts** with **30 / 70** reference lines in the expander.
"""
                )
                if st.button("📊 Show portfolio RSI", key="btn_rsi_analyze"):
                    st.session_state.rsi_flag = True
                if not st.session_state.rsi_flag:
                    st.caption("Click to compute and plot RSI per ticker.")
                else:
                    rsi_summary = {}
                    for ticker in st.session_state.df["Ticker"].astype(str).str.strip().unique():
                        rsi = compute_rsi(ticker)
                        if rsi is not None and not rsi.empty and pd.notna(rsi.iloc[-1]):
                            rsi_summary[ticker] = (float(rsi.iloc[-1]), rsi)
                    if rsi_summary:
                        st.markdown("##### Latest RSI by ticker")
                        for t, (rv, _) in rsi_summary.items():
                            st.markdown(f"- **Ticker:** {t} — **RSI:** **{rv:.1f}**")
                        st.markdown("---")
                        with st.expander("📈 RSI time series"):
                            for t, (_, series) in rsi_summary.items():
                                fig_r, ax_r = plt.subplots(figsize=(10, 4))
                                ax_r.plot(series.index, series.values, color="#F39C12", label="RSI (14)")
                                ax_r.axhline(70, color="#E74C3C", linestyle="--", linewidth=1, label="Overbought (70)")
                                ax_r.axhline(30, color="#3498DB", linestyle="--", linewidth=1, label="Oversold (30)")
                                ax_r.set_title(f"{t} — RSI (14)")
                                ax_r.set_xlabel("Date")
                                ax_r.set_ylabel("RSI")
                                ax_r.set_ylim(0, 100)
                                ax_r.grid(True, alpha=0.3)
                                ax_r.legend(loc="upper left")
                                fig_r.tight_layout()
                                st.pyplot(fig_r, use_container_width=True)
                    else:
                        st.warning("Could not compute RSI for any ticker.")
            with subtab7:
                st.markdown("##### MACD")
                st.markdown("##### Key points")
                st.markdown(
                    """
- **MACD** blends **trend and momentum**: it compares a **faster EMA (12)** of price to a **slower EMA (26)**, then smooths that difference with a **signal line (9)**.
- **MACD line above the signal** is often read as **bullish momentum**; **below** as **bearish**. **Histogram** (MACD − signal) shows whether that gap is **widening or shrinking**.
- **Crossovers** (MACD crossing signal) are widely watched but **lag** price; they work best as **context** with trend and risk checks.
- **What this tab does:** Builds **MACD (12,26,9)** from daily closes for each ticker and plots **MACD, signal, and histogram** over time in the expander.
"""
                )
                if st.button("📊 Show portfolio MACD", key="btn_macd_analyze"):
                    st.session_state.macd_flag = True
                if not st.session_state.macd_flag:
                    st.caption("Click to compute and plot MACD per ticker.")
                else:
                    macd_data = {}
                    for ticker in st.session_state.df["Ticker"].astype(str).str.strip().unique():
                        m = compute_macd(ticker)
                        if m is not None and not m.empty:
                            macd_data[ticker] = m
                    if macd_data:
                        with st.expander("📈 MACD time series"):
                            for t, m in macd_data.items():
                                fig_m, ax_m = plt.subplots(figsize=(10, 4))
                                ax_m.plot(m.index, m["MACD"], label="MACD", color="#1F77B4")
                                ax_m.plot(m.index, m["Signal"], label="Signal", color="#FF7F0E")
                                ax_m.bar(m.index, m["Histogram"], label="Histogram", color="#95A5A6", alpha=0.4)
                                ax_m.axhline(0, color="#666666", linewidth=1)
                                ax_m.set_title(f"{t} — MACD (12, 26, 9)")
                                ax_m.set_xlabel("Date")
                                ax_m.set_ylabel("Value")
                                ax_m.grid(True, alpha=0.3)
                                ax_m.legend(loc="upper left")
                                fig_m.tight_layout()
                                st.pyplot(fig_m, use_container_width=True)
                    else:
                        st.warning("Could not compute MACD for any ticker.")
            with subtab8:
                st.markdown("##### MACD + CMF + EMA + Supertrend")
                st.markdown("##### Key points")
                st.markdown(
                    """
- This setup combines **trend** (EMA), **momentum** (MACD), **money flow** (CMF), and **trend state** (Supertrend) into one rule set.
- Entry signals use a **MACD double-cross sequence** (TradeSmart style):
    one cross in the opposite direction and then a confirming cross in the trade direction,
    with zero-line re-arm and zero-touch skip logic.
- A **Bullish** entry additionally requires: CMF > 0, Close > EMA, and bullish Supertrend.
- A **Bearish** entry additionally requires: CMF < 0, Close < EMA, and bearish Supertrend.
- **What this tab does:** Computes these indicators for each portfolio ticker and shows the latest signal plus a full 3-panel chart.
"""
                )
                if st.button("📊 Show strategy signals", key="btn_tradesmart_analyze"):
                    st.session_state.tradesmart_flag = True
                if not st.session_state.tradesmart_flag:
                    st.caption("Click to compute MACD+CMF+EMA+Supertrend signals per ticker.")
                else:
                    strategy_data = {}
                    for ticker in st.session_state.df["Ticker"].astype(str).str.strip().unique():
                        ind_df, summary = compute_macd_cmf_ema_supertrend(ticker)
                        if ind_df is not None and summary is not None:
                            strategy_data[ticker] = (ind_df, summary)

                    if strategy_data:
                        st.markdown("##### Latest strategy signal by ticker")
                        signal_icon = {"Bullish": "🟢", "Bearish": "🔴", "Neutral": "⚪"}
                        for t, (_, s) in strategy_data.items():
                            icon = signal_icon.get(s["strategy_signal"], "⚪")
                            recent = s.get("recent_signal", "Neutral")
                            recent_dt = s.get("recent_signal_date")
                            recent_txt = f"{recent} on {recent_dt}" if recent_dt else recent
                            st.markdown(
                                f"- **Ticker:** {t} — **Signal:** **{s['strategy_signal']}** {icon} "
                                f"| **Most recent trigger:** **{recent_txt}** "
                                f"(CMF: {s['cmf']:.2f}, MACD: {s['macd']:.2f}, Signal: {s['signal']:.2f})"
                            )
                        st.markdown("---")
                        with st.expander("📈 Strategy diagnostics (price + MACD + CMF)"):
                            for t, (ind_df, s) in strategy_data.items():
                                st.markdown(f"**{t}**")
                                c1, c2, c3, c4 = st.columns(4)
                                c1.metric("Close", f"{s['close']:.2f}")
                                c2.metric("EMA", f"{s['ema']:.2f}")
                                c3.metric("CMF", f"{s['cmf']:.2f}")
                                c4.metric("Supertrend", "Bullish" if s["st_bull"] else "Bearish")
                                fig_ts = plot_macd_cmf_ema_supertrend(ind_df, t)
                                if fig_ts is not None:
                                    st.pyplot(fig_ts, use_container_width=True)
                    else:
                        st.warning("Could not compute MACD+CMF+EMA+Supertrend for any ticker.")

        with tab5:
            st.markdown("### ✨ AI Recommendations")
            st.caption(
                "Volatility, P/E, beta, Sharpe, and MACD for your holdings — context only "
                "(not personalized investment advice)."
            )
            with st.expander("ℹ️ What these metrics mean (read me first)", expanded=False):
                st.markdown(
                    """
**Latest volatility (%)** — How much the price has fluctuated recently (here: annualized from daily moves). **Higher** usually means **riskier / bumpier** rides; **lower** means **calmer** price action. It does not say whether the investment is “good” or “bad.”

**P/E ratio (price-to-earnings)** — Stock price divided by **earnings per share** (trailing, from Yahoo when available). Often read as **how much investors pay per unit of past profit**. **Very high** P/E can mean growth expectations—or stretched valuation. **No P/E** often means **no positive earnings**, or the asset is an **ETF / fund / crypto** where the label does not apply the same way.

**Beta** — How sensitive returns have been **versus the broad market** (from Yahoo’s `beta`, when available). **Above ~1** tends to mean **more market-like swings**; **below ~1** often means **milder** moves vs. the benchmark. **No beta** is common for some ETFs and alternative assets.

**Sharpe ratio** — **Excess return per unit of volatility** over the recent window (here: daily returns, risk-free rate ≈ 0, annualized). **Higher** can mean **better risk-adjusted performance** in that period; **negative** means returns were **weak vs. volatility**. It is **very period-dependent**.

**MACD crossover** — **MACD** compares two trend-following averages of price; the **signal** line smooths MACD. When **MACD is above** the signal, some read that as **stronger short-term momentum** (**Bullish** here); **below** as **weaker** (**Bearish**). These signals **lag** price and are **not** buy/sell rules by themselves.
"""
                )
            tickers_ai = [
                t
                for t in st.session_state.df["Ticker"].astype(str).str.strip().unique().tolist()
                if t and str(t).lower() != "nan"
            ]

            with st.spinner("⏳ Loading metrics…"):
                vol_map = {}
                for t in tickers_ai:
                    ph, _ = get_history(t)
                    if ph is not None and not ph.empty:
                        vv = compute_volatility_from_price_history(ph)
                        if vv is not None:
                            vol_map[t] = vv

                pe_map = {}
                for t in tickers_ai:
                    pe = compute_pe_ratio(t)
                    if pd.notna(pe) and pe > 0:
                        pe_map[t] = float(pe)

                beta_map = {}
                for t in tickers_ai:
                    b = beta_values(t)
                    if pd.notna(b):
                        beta_map[t] = float(b)

                sharpe_map = {}
                for t in tickers_ai:
                    s = compute_sharpe_ratio(t)
                    if s is not None:
                        sharpe_map[t] = s

                macd_map = {}
                for t in tickers_ai:
                    m = compute_macd(t)
                    if m is None or m.empty:
                        continue
                    last = m.iloc[-1]
                    mv = float(last["MACD"])
                    sv = float(last["Signal"])
                    if mv > sv:
                        tag, status_emoji = "Bullish", "🟢"
                    elif mv < sv:
                        tag, status_emoji = "Bearish", "🔴"
                    else:
                        tag, status_emoji = "Neutral", "⚪"
                    macd_map[t] = (mv, sv, tag, status_emoji)

            st.markdown("#### Latest volatility")
            st.markdown(
                """
*Uses ~1 year of daily prices. **Annualized volatility %** summarizes how wide daily up/down moves have been. Compare across holdings to see which names have been more “jumpy.”*
"""
            )
            if vol_map:
                for t in tickers_ai:
                    if t not in vol_map:
                        continue
                    st.markdown(
                        f"- **Ticker:** {t} — **Latest volatility:** **{vol_map[t]:.1f}%** 📉"
                    )
            else:
                st.info("No volatility figures computed — check tickers and Yahoo data.")

            st.markdown("---")
            st.markdown("#### P/E ratio")
            st.markdown(
                """
***Trailing P/E** from Yahoo when the stock has **positive** trailing EPS. **Warnings** mean no usable P/E (e.g. losses, ETF, or crypto) — not necessarily a problem, just “not applicable” like a simple stock P/E.*
"""
            )
            for t in tickers_ai:
                if t in pe_map:
                    st.markdown(f"- **{t}** P/E Ratio: **{pe_map[t]:.2f}** 📊")
                else:
                    st.markdown(
                        f"⚠️ Warning: the ticker **{t}** has no P/E Ratio (negative earnings, ETF or Crypto)"
                    )

            st.markdown("---")
            st.markdown("#### Beta")
            st.markdown(
                """
*From Yahoo **beta**: sensitivity to the **market index** Yahoo uses for that symbol. Use it as a **rough** volatility-vs-market label, not a full risk model.*
"""
            )
            for t in tickers_ai:
                if t in beta_map:
                    st.markdown(f"- **Ticker:** {t} — **Beta:** **{beta_map[t]:.2f}**")
                else:
                    st.markdown(f"⚠️ Warning: the ticker **{t}** has no Beta")

            st.markdown("---")
            st.markdown("#### Sharpe ratio")
            st.markdown(
                """
*Computed from **daily returns** over the same history window as elsewhere in this app. **Sharpe** mixes **return** and **volatility**; the sentences below flag **high volatility** (≥ 25% in this tab) when Sharpe is still **positive**.*
"""
            )
            for t in tickers_ai:
                if t not in sharpe_map:
                    continue
                s = sharpe_map[t]
                v = vol_map.get(t)
                if v is not None and v >= 25.0 and s >= 0:
                    st.markdown(
                        f"**{t}** has Sharpe ratio **{s:.1f}**: positive return but with high volatility. ⚠️"
                    )
                elif s >= 0:
                    st.markdown(
                        f"**{t}** has Sharpe ratio **{s:.1f}**: positive risk-adjusted return vs. volatility. 📈"
                    )
                else:
                    st.markdown(
                        f"**{t}** has Sharpe ratio **{s:.1f}**: negative excess return vs. volatility over this window. 📉"
                    )

            st.markdown("---")
            st.markdown("#### MACD crossover")
            st.markdown(
                """
*Standard **MACD(12,26,9)**: **MACD line** vs **signal line** on the latest day. **Bullish** = MACD above signal; **Bearish** = below; **Neutral** = equal. Good for **context**; confirm with fundamentals and risk limits.*
"""
            )
            if macd_map:
                for t in tickers_ai:
                    if t not in macd_map:
                        continue
                    mv, sv, tag, status_emoji = macd_map[t]
                    st.markdown(f"##### {t} — MACD crossover 📊")
                    st.markdown(f"- **MACD:** {mv:.1f}")
                    st.markdown(f"- **Signal:** {sv:.1f}")
                    st.markdown(f"- **Status:** **{tag}** {status_emoji}")
            else:
                st.info("No MACD data computed — check tickers and Yahoo history.")

        with tab6:
            ticker_input = st.text_input(
                "Enter New Ticker symbols 🏷️",
                placeholder="NVDA, TSLA",
                key="idea_ticker_input",
            )

            if st.button("+ Submit", key="btn_submit_idea_tickers", type="secondary"):
                raw_symbols = [s.strip().upper() for s in ticker_input.replace(";", ",").split(",")]
                seen = set()
                symbols = []
                for s in raw_symbols:
                    if not s:
                        continue
                    s = _IDEA_TICKER_ALIASES.get(s, s)
                    if s not in seen:
                        seen.add(s)
                        symbols.append(s)
                if not symbols:
                    st.error("Please enter at least one valid ticker symbol.")
                else:
                    added = []
                    invalid = []
                    for sym in symbols:
                        if sym in st.session_state.idea_tickers:
                            continue
                        ok = False
                        try:
                            hist = yf.Ticker(sym).history(period="5d")
                            if hist is not None and not hist.empty:
                                ok = True
                            else:
                                ph_try, _ = get_history(sym, session=_yahoo_session())
                                if ph_try is not None and not ph_try.empty:
                                    ok = True
                        except Exception:
                            ph_try, _ = get_history(sym, session=_yahoo_session())
                            ok = ph_try is not None and not ph_try.empty
                        if ok:
                            st.session_state.idea_tickers.append(sym)
                            added.append(sym)
                        else:
                            invalid.append(sym)

                    if added:
                        st.success(f"Added: {', '.join(added)}")
                    if invalid:
                        st.warning(
                            "Ticker not found or unavailable: "
                            + ", ".join(invalid)
                            + ". Try the Yahoo Finance symbol (e.g. Oracle → **ORCL**)."
                        )
                    if not added and not invalid:
                        st.info("No new symbols were added.")

            st.markdown(
                '<h2 style="color:#C2185B;font-weight:700;font-size:1.65rem;'
                'margin:1.1rem 0 0.5rem 0;line-height:1.25;">'
                "Portfolio &amp; New Instruments Analysis 🔗"
                "</h2>",
                unsafe_allow_html=True,
            )

            sess = _yahoo_session()
            idea_syms = list(st.session_state.idea_tickers)

            if idea_syms:
                as_of = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.caption(
                    f"Live assessment from current Yahoo price history and fundamentals (as of **{as_of}**). "
                    "Re-runs on every **+ Submit** or page refresh — not a fixed template. Educational only."
                )

                with st.spinner("⏳ Fetching live data and writing analysis…"):
                    for idx, sym in enumerate(idea_syms, start=1):
                        ph, info = get_history(sym, session=sess)
                        if ph is None or ph.empty or "Close" not in ph.columns:
                            st.warning(
                                f"**{sym}:** Could not load enough history for a live write-up. "
                                "Check the symbol on Yahoo Finance."
                            )
                            continue
                        st.markdown(format_new_instrument_assessment(sym, ph, info, item_index=idx))
                        if idx < len(idea_syms):
                            st.markdown("---")

                    idea_prices = get_prices_batch(idea_syms, session=sess)
                    if not idea_prices:
                        idea_prices = get_prices_via_chart_api(idea_syms, session=sess)

                st.markdown("#### Saved ticker ideas")
                st.markdown(", ".join(f"`{t}`" for t in idea_syms))

                st.markdown("#### Latest prices")
                if idea_prices:
                    for sym in idea_syms:
                        if sym in idea_prices:
                            st.markdown(f"- **{sym}**: {idea_prices[sym]:.2f} (native currency)")
                        else:
                            st.markdown(f"- **{sym}**: price unavailable")
                else:
                    st.info("Could not load prices right now. Try again in a moment.")

                st.markdown("---")
                st.markdown("#### TradeSmart strategy trades (paper)")
                st.caption(
                    "Generates paper trade actions from MACD+CMF+EMA+Supertrend signals for your candidate tickers. "
                    "Educational only, not live broker execution."
                )

                run_trade_gen = st.button("⚙️ Generate strategy trades", key="btn_idea_strategy_trades")
                generated_signals = {}
                if run_trade_gen:
                    trade_rows = []
                    for sym in idea_syms:
                        ind_df, summary = compute_macd_cmf_ema_supertrend(sym)
                        if ind_df is None or summary is None:
                            continue
                        generated_signals[sym] = summary.get("strategy_signal", "Neutral")
                        trades_df, state = build_tradesmart_paper_trades(sym, ind_df, lookback_bars=220)
                        now_signal = summary.get("strategy_signal", "Neutral")
                        recent_signal = summary.get("recent_signal", "Neutral")
                        recent_date = summary.get("recent_signal_date") or "n/a"

                        if now_signal == "Bullish":
                            suggested_action = "BUY"
                        elif now_signal == "Bearish":
                            suggested_action = "SELL"
                        elif recent_signal == "Bullish":
                            suggested_action = "HOLD_LONG_BIAS"
                        elif recent_signal == "Bearish":
                            suggested_action = "HOLD_SHORT_BIAS"
                        else:
                            suggested_action = "WAIT"

                        trade_rows.append(
                            {
                                "Ticker": sym,
                                "Current Signal": now_signal,
                                "Recent Signal": recent_signal,
                                "Recent Signal Date": recent_date,
                                "Suggested Action": suggested_action,
                                "Position State": state.get("position", "Flat"),
                                "Last Action": state.get("last_action", "None"),
                                "CMF": summary.get("cmf", np.nan),
                                "MACD": summary.get("macd", np.nan),
                                "Signal": summary.get("signal", np.nan),
                            }
                        )

                        with st.expander(f"{sym} trade log"):
                            if trades_df is None or trades_df.empty:
                                st.info("No entry events were triggered in the selected lookback window.")
                            else:
                                st.dataframe(trades_df, use_container_width=True)
                            fig_ts = plot_macd_cmf_ema_supertrend(ind_df, sym)
                            if fig_ts is not None:
                                st.pyplot(fig_ts, use_container_width=True)

                    if trade_rows:
                        trades_summary_df = pd.DataFrame(trade_rows)
                        st.markdown("##### Strategy trade summary")
                        st.dataframe(trades_summary_df, use_container_width=True)
                    else:
                        st.warning("Could not generate strategy trades for the saved candidate tickers.")

                st.markdown("##### Alpaca execution (paper/live)")
                st.caption(
                    "Executes current TradeSmart signals in Alpaca. Default behavior is long-only: bullish opens/holds long, bearish closes long."
                )
                exec_mode = st.radio(
                    "Broker mode",
                    ["paper", "live"],
                    horizontal=True,
                    key="idea_alpaca_exec_mode",
                )
                exec_qty = st.number_input(
                    "Order quantity per symbol",
                    min_value=1,
                    value=1,
                    step=1,
                    key="idea_alpaca_exec_qty",
                )
                allow_short_entries = st.checkbox(
                    "Allow opening short positions on bearish signals",
                    value=False,
                    key="idea_alpaca_allow_short",
                )
                if exec_mode == "live":
                    st.warning("Live mode sends real orders. Use only after verifying API keys, symbol list, and market status.")
                    live_confirm = st.text_input(
                        "Type LIVE to confirm real execution",
                        key="idea_live_confirm_text",
                    )
                else:
                    live_confirm = ""

                run_exec = st.button("🚀 Execute strategy on Alpaca", key="btn_idea_execute_alpaca")
                if run_exec:
                    if exec_mode == "live" and live_confirm.strip() != "LIVE":
                        st.error("Live execution not confirmed. Type LIVE exactly to continue.")
                    else:
                        if not generated_signals:
                            for sym in idea_syms:
                                _, summary = compute_macd_cmf_ema_supertrend(sym)
                                if summary is not None:
                                    generated_signals[sym] = summary.get("strategy_signal", "Neutral")

                        if not generated_signals:
                            st.warning("No strategy signals available to execute.")
                        else:
                            with st.spinner("⏳ Sending orders to Alpaca…"):
                                try:
                                    client = get_alpaca_trading_client(exec_mode)
                                except Exception as e:
                                    st.error(f"Could not initialize Alpaca client: {e}")
                                    client = None

                                if client is not None:
                                    execution_rows = []
                                    for sym, sig in generated_signals.items():
                                        res = execute_tradesmart_signal_on_alpaca(
                                            client,
                                            sym,
                                            sig,
                                            order_qty=int(exec_qty),
                                            allow_short_entries=allow_short_entries,
                                        )
                                        execution_rows.append(res)

                                    if execution_rows:
                                        st.markdown("###### Execution results")
                                        st.dataframe(pd.DataFrame(execution_rows), use_container_width=True)
                                    else:
                                        st.info("No orders were sent.")
            else:
                st.caption(
                    "After you add tickers with **+ Submit**, a live write-up is generated here from the latest data."
                )
                st.info("No ticker ideas saved yet. Enter symbols above and click + Submit.")

            st.markdown("---")
            st.markdown("#### Portfolio analysis")
            st.caption(
                "Side-by-side KPI snapshots for current holdings and candidate tickers (educational only)."
            )
            holdings = st.session_state.df
            hold_tickers = [
                t
                for t in holdings["Ticker"].astype(str).str.strip().unique().tolist()
                if t and str(t).lower() != "nan"
            ]
            hold_assets = holdings.set_index("Ticker")["Asset"].astype(str).to_dict()
            hold_prices = None
            if "Price Today (EUR)" in holdings.columns:
                hold_prices = [
                    holdings.loc[holdings["Ticker"].astype(str).str.strip() == t, "Price Today (EUR)"].iloc[0]
                    for t in hold_tickers
                ]
            with st.spinner("⏳ Building portfolio analysis…"):
                kpi_holdings = build_portfolio_kpi_dataframe(
                    hold_tickers,
                    assets=[hold_assets.get(t, t) for t in hold_tickers],
                    prices_today=hold_prices,
                    session=sess,
                )
                kpi_candidates = build_portfolio_kpi_dataframe(idea_syms, session=sess)

            if not kpi_holdings.empty:
                st.markdown("##### Current holdings")
                st.dataframe(kpi_holdings, use_container_width=True)
            else:
                st.info("No holdings data available for portfolio analysis.")

            if not kpi_candidates.empty:
                st.markdown("##### Candidate tickers")
                st.dataframe(kpi_candidates, use_container_width=True)
            else:
                st.info("No candidate tickers data available for portfolio analysis.")

            st.markdown("---")
            st.markdown("#### Overall portfolio note")
            st.caption(
                "Synthesizes your **uploaded holdings** plus any **saved ticker ideas** "
                "(educational only — not investment advice)."
            )
            with st.spinner("⏳ Building portfolio summary…"):
                try:
                    portfolio_note = generate_portfolio_ai_markdown(kpi_holdings, kpi_candidates)
                except ValueError:
                    portfolio_note = format_overall_portfolio_note_heuristic(
                        pd.concat([kpi_holdings, kpi_candidates], ignore_index=True)
                        if not kpi_candidates.empty
                        else kpi_holdings
                    )
            st.markdown(portfolio_note)
