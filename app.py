"""
Stock Analysis – Streamlit app.
Run from terminal:  streamlit run app.py
"""
import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from utils import get_fx_rate, get_price_local, get_prices_batch, get_prices_via_chart_api, _yahoo_session, compute_moving_averages, plot_moving_averages, get_history

st.set_page_config(page_title="Stock Analysis", page_icon=":chart_with_upwards_trend:")
st.title("📊 Financial Performance Analysis")
st.markdown("🧾 Upload a CSV of your holdings to view gains and prices, plus recommendations 🤖")
st.markdown("## 📁 Upload your CSV file")
uploaded_file = st.file_uploader("Upload your CSV file", type=["csv"])


if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False
if "flag" not in st.session_state:
    st.session_state.flag = False

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
        tab1, tab2, tab3, tab4 = st.tabs(["Gains", "Stock Updates", "Export Data", "Stock Analysis"])
        with tab1:
            for col in ["Units", "Purchase Price", "Value Last Update"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

            # Only fetch prices when user clicks — keeps page load instant, no white screen
            if "load_prices" not in st.session_state:
                st.session_state.load_prices = False
            if st.button("Load current prices 🔎", key="btn_load_prices"):
                st.session_state.load_prices = True

            if st.session_state.load_prices:
                with st.spinner("Loading prices…"):
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
            update = st.radio("Do you have any updates for the portfolio?", ["Yes", "No"], horizontal=True)
            if update == "Yes":
                st.markdown("## 📝 Stock Asset Details")
                selected_asset = st.selectbox("Select an asset", st.session_state.df["Asset"].unique().tolist())
                
                # Ask for the units and price
                changed_units = st.number_input(
                    "How many units were bought (2) / sold (-2):",
                    value=0.0,
                    step=0.01,
                    format="%.2f",
                    help="Positive = bought, negative = sold.",
                )
                new_purchase_price = st.number_input(
                    "What was the purchase price per unit (EUR):",
                    min_value=0.0,
                    value=0.0,
                    step=0.01,
                    format="%.2f",
                )    
                
                if st.button("Update Asset"):
                    if selected_asset and changed_units != 0 and new_purchase_price > 0:
                        # Update units and average purchase price
                        idx = st.session_state.df[st.session_state.df["Asset"] == selected_asset].index[0]
                        old_units = st.session_state.df.at[idx, "Units"]
                        st.session_state.df.at[idx, "Units"] = old_units + changed_units

                        # Update the average purchase price
                        old_purchase_price = st.session_state.df.at[idx, "Purchase Price"]
                        st.session_state.df.at[idx, "Purchase Price"] = (old_purchase_price * old_units + changed_units * new_purchase_price) / (old_units + changed_units)

                        st.success(f"✅ Updated {selected_asset}:{old_units + changed_units} units @ {st.session_state.df.at[idx, 'Purchase Price']}")

                    else:
                        st.error("❗ Please fill in all fields and select an asset to update.")

            # Add new assets to the portfolio
            new_asset = st.radio("Did you add any new assets to the portfolio? (y/n) ", ["Yes", "No"], horizontal=True)
            if new_asset == "Yes":
                st.markdown("## 📝 New Asset Details")
                asset_name = st.text_input("Asset name:")
                ticker = st.text_input("Ticker:")
                currency = st.selectbox("Currency Yahoo:", ["EUR", "USD", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY", "SEK", "NZD"], index=0)
                units = st.number_input("Units: ", min_value=0.000001, step=0.000001)
                purchase_price = st.number_input("Purchase Price: ", min_value=0.0, step=0.000001)

                if st.button("Add Asset"):
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
                            st.error("❓ Ticker not found.")
                    else:
                        st.error("❗ Please fill in all fields and select an asset to update.")

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
            if st.button("Analyze", key="btn_stock_analyze"):
                st.session_state.flag = True
            subtab1, subtab2 = st.tabs(["Moving Averages", "Volatility"])
            with subtab1:
                st.markdown("#### Moving averages")
                if not st.session_state.flag:
                    st.info("Click **Analyze** above to load charts for each holding.")
                else:
                    for ticker in st.session_state.df["Ticker"].astype(str).str.strip().unique():
                        price_history, latest = compute_moving_averages(ticker)
                        if price_history is None:
                            st.warning(f"Could not load historical data for {ticker}.")
                            continue
                        fig = plot_moving_averages(price_history, ticker)
                        if fig is not None:
                            st.pyplot(fig, use_container_width=True)
                        if latest is not None:
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("Latest", f"{latest['latest_price']:.2f}" if pd.notna(latest["latest_price"]) else "—")
                            c2.metric("MA50", f"{latest['ma50']:.2f}" if pd.notna(latest["ma50"]) else "—")
                            c3.metric("MA100", f"{latest['ma100']:.2f}" if pd.notna(latest["ma100"]) else "—")
                            c4.metric("MA200", f"{latest['ma200']:.2f}" if pd.notna(latest["ma200"]) else "—")
            with subtab2:
                st.markdown("#### Volatility")
                st.caption("Volatility view can be added here.")
