"""
Simple interactive CLI for stock portfolio analysis.
Run: python cli_app.py
"""
import os
import sys
import subprocess
import time
from pathlib import Path
from datetime import datetime

SUPPORTED_MIN = (3, 10)
SUPPORTED_MAX_EXCLUSIVE = (3, 14)


def _ensure_supported_python() -> None:
    v = sys.version_info
    if (v.major, v.minor) < SUPPORTED_MIN or (v.major, v.minor) >= SUPPORTED_MAX_EXCLUSIVE:
        raise SystemExit(
            "Unsupported Python version "
            f"{v.major}.{v.minor}. "
            "Use Python 3.10-3.13 (recommended: 3.11, e.g. .venv311)."
        )


_ensure_supported_python()

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import yfinance as yf
from dotenv import load_dotenv

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
    compute_volatility_from_price_history,
    plot_volatility,
    compute_pe_ratio,
    beta_values,
    compute_sharpe_ratio,
    compute_rsi,
    compute_macd,
    format_new_instrument_assessment,
)

load_dotenv(Path(__file__).resolve().parent / ".env")

# Common Yahoo symbol aliases for the idea input
_IDEA_TICKER_ALIASES = {"ORACLE": "ORCL"}

# Curated large-cap US defense/aerospace universe for themed optimization runs.
_DEFENSE_UNIVERSE = [
    "LMT",   # Lockheed Martin
    "NOC",   # Northrop Grumman
    "RTX",   # RTX
    "GD",    # General Dynamics
    "BA",    # Boeing
    "LHX",   # L3Harris
    "HII",   # Huntington Ingalls
    "TXT",   # Textron
    "LDOS",  # Leidos
    "KTOS",  # Kratos
    "AVAV",  # AeroVironment
    "MRCY",  # Mercury Systems
    "CW",    # Curtiss-Wright
    "BWXT",  # BWX Technologies
    "OSIS",  # OSI Systems
    "HEI",   # HEICO
    "SAIC",  # SAIC
    "AXON",  # Axon (public safety/defense-adjacent)
]

REQUIRED_COLUMNS = [
    "Asset",
    "Ticker",
    "Currency Yahoo",
    "Units",
    "Purchase Price",
    "Value Last Update",
]


def _prompt(msg, default=None):
    if default:
        msg = f"{msg} [{default}]: "
    else:
        msg = f"{msg}: "
    val = input(msg).strip()
    return val if val else default


def _prompt_float(msg, default=None):
    while True:
        val = _prompt(msg, default)
        try:
            return float(val)
        except (TypeError, ValueError):
            print("Invalid number. Try again.")


def _prompt_int(msg, default=None):
    while True:
        val = _prompt(msg, default)
        try:
            return int(val)
        except (TypeError, ValueError):
            print("Invalid number. Try again.")


def _ensure_columns(df):
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        print("CSV missing required columns:")
        print(", ".join(missing))
        print("Expected columns:")
        print(", ".join(REQUIRED_COLUMNS))
        return False
    return True


def _load_csv(path):
    if not path or not os.path.exists(path):
        print("File not found.")
        return None
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    if not _ensure_columns(df):
        return None
    return df


def _load_prices(df):
    df = df.copy()
    for col in ["Units", "Purchase Price", "Value Last Update"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    try:
        session = _yahoo_session()
        fx_cache = {}
        for fx in df["Currency Yahoo"].dropna().unique():
            fx_cache[fx] = 1.0 if fx == "EUR" else get_fx_rate(fx, session=session)
        tickers = df["Ticker"].astype(str).str.strip().unique().tolist()
        prices_native = get_prices_batch(tickers, session=session)
        if not prices_native:
            prices_native = get_prices_via_chart_api(tickers, session=session)

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
        print(f"Warning: could not load prices: {e}")

    df["Value Today (EUR)"] = df["Price Today (EUR)"] * df["Units"]
    df["Gain since Last Update (EUR)"] = df["Value Today (EUR)"] - df["Value Last Update"]
    cost_basis = df["Units"] * df["Purchase Price"]
    df["Gain since Purchase (EUR)"] = df["Value Today (EUR)"] - cost_basis
    value_last = df["Value Last Update"].replace(0, np.nan)
    cost_basis_safe = cost_basis.replace(0, np.nan)
    df["Gain since Last Update (%)"] = (
        df["Gain since Last Update (EUR)"] / value_last * 100
    ).replace([np.inf, -np.inf], np.nan)
    df["Gain since Purchase (%)"] = (
        df["Gain since Purchase (EUR)"] / cost_basis_safe * 100
    ).replace([np.inf, -np.inf], np.nan)

    return df


def _print_gains(df):
    gain_cols = [
        "Gain since Last Update (EUR)",
        "Gain since Purchase (EUR)",
        "Gain since Purchase (%)",
    ]
    columns = ["Asset", "Ticker"] + gain_cols
    cost_basis = df["Units"] * df["Purchase Price"]
    total_cost = cost_basis.sum()
    total_gain_last = df["Gain since Last Update (EUR)"].sum()
    total_gain_purchase = df["Gain since Purchase (EUR)"].sum()
    total_gain_pct = (total_gain_purchase / total_cost * 100) if total_cost else 0.0
    totals = {
        "Asset": "Total",
        "Ticker": "",
        "Gain since Last Update (EUR)": float(total_gain_last),
        "Gain since Purchase (EUR)": float(total_gain_purchase),
        "Gain since Purchase (%)": float(total_gain_pct),
    }
    report = pd.concat([df[columns], pd.DataFrame([totals])], ignore_index=True)
    print("\nSnapshot of financial performance")
    print(report.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


def _update_asset(df):
    assets = df["Asset"].astype(str).tolist()
    if not assets:
        print("No assets found.")
        return df
    print("\nSelect asset to update:")
    for i, name in enumerate(assets, start=1):
        print(f"  {i}. {name}")
    idx = _prompt_int("Enter number", 1) - 1
    if idx < 0 or idx >= len(assets):
        print("Invalid selection.")
        return df

    selected_asset = assets[idx]
    changed_units = _prompt_float("Units bought (+) or sold (-)", 0.0)
    new_purchase_price = _prompt_float("Purchase price per unit (EUR)", 0.0)
    if changed_units == 0 or new_purchase_price <= 0:
        print("No update applied. Units and price must be non-zero.")
        return df

    row_idx = df[df["Asset"] == selected_asset].index[0]
    old_units = float(df.at[row_idx, "Units"])
    old_price = float(df.at[row_idx, "Purchase Price"])
    new_units = old_units + changed_units
    if abs(new_units) < 1e-9:
        print("Update would result in zero units. Skipping average price update.")
        df.at[row_idx, "Units"] = new_units
        return df

    avg_price = (old_price * old_units + changed_units * new_purchase_price) / new_units
    df.at[row_idx, "Units"] = new_units
    df.at[row_idx, "Purchase Price"] = avg_price
    print(f"Updated {selected_asset}: {new_units} units @ {avg_price:.4f}")
    return df


def _add_asset(df):
    asset_name = _prompt("Asset name")
    ticker = _prompt("Yahoo ticker (e.g. AAPL)")
    currency = _prompt("Currency (Yahoo)", "EUR")
    units = _prompt_float("Units", 0.0)
    purchase_price = _prompt_float("Purchase price per unit (EUR)", 0.0)
    if not asset_name or not ticker or units <= 0 or purchase_price <= 0:
        print("Missing or invalid fields. Nothing added.")
        return df

    try:
        info = yf.Ticker(ticker).info
        if not isinstance(info, dict) or "shortName" not in info:
            print("Ticker not found on Yahoo. Nothing added.")
            return df
    except Exception:
        print("Ticker lookup failed. Nothing added.")
        return df

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
        "Profit Last Update": np.nan,
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    print(f"Added {asset_name}.")
    return df


def _export_csv(df, default_path=None):
    path = _prompt("Export file path", default_path)
    if not path:
        print("Export cancelled.")
        return
    export_df = df.copy()
    if "Price Today (EUR)" in export_df.columns:
        export_df["Price Last Update"] = export_df["Price Today (EUR)"]
    export_df["Date Last Update"] = datetime.now().strftime("%Y-%m-%d")
    n_cols = min(10, export_df.shape[1])
    export_df.iloc[:, :n_cols].to_csv(path, index=False)
    print(f"Exported: {path}")


def _save_figure(fig, out_dir, name):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    fig.savefig(path, dpi=150)
    print(f"Saved chart: {path}")


def _analysis_menu(df):
    tickers = df["Ticker"].astype(str).str.strip().unique().tolist()
    if not tickers:
        print("No tickers to analyze.")
        return

    out_dir = _prompt("Charts output folder", "charts")
    while True:
        print("\nAnalysis menu")
        print("  1. Moving averages")
        print("  2. Volatility")
        print("  3. P/E ratio")
        print("  4. Beta")
        print("  5. Sharpe ratio")
        print("  6. RSI")
        print("  7. MACD")
        print("  8. Back")
        choice = _prompt("Select option")

        if choice == "1":
            for t in tickers:
                history, latest = compute_moving_averages(t)
                if history is None or latest is None:
                    print(f"No history for {t}.")
                    continue
                lp = latest.get("latest_price", np.nan)
                for key in ("ma50", "ma100", "ma200"):
                    tag = latest_vs_ma_label(lp, latest.get(key))
                    print(f"{t} {key.upper()}: {latest.get(key, np.nan):.2f} ({tag})")
                fig = plot_moving_averages(history, t)
                if fig is not None:
                    _save_figure(fig, out_dir, f"{t}_ma.png")
        elif choice == "2":
            for t in tickers:
                ph, _ = get_history(t)
                v = compute_volatility_from_price_history(ph) if ph is not None else None
                if v is None:
                    print(f"No volatility for {t}.")
                    continue
                print(f"{t} volatility: {v:.1f}%")
                if ph is not None:
                    fig = plot_volatility(ph, t)
                    if fig is not None:
                        _save_figure(fig, out_dir, f"{t}_volatility.png")
        elif choice == "3":
            for t in tickers:
                pe = compute_pe_ratio(t)
                if pd.notna(pe) and pe > 0:
                    print(f"{t} P/E: {pe:.1f}")
                else:
                    print(f"{t} P/E: n/a")
        elif choice == "4":
            for t in tickers:
                b = beta_values(t)
                if pd.notna(b):
                    print(f"{t} beta: {b:.2f}")
                else:
                    print(f"{t} beta: n/a")
        elif choice == "5":
            for t in tickers:
                s = compute_sharpe_ratio(t)
                if s is not None:
                    print(f"{t} Sharpe: {s:.2f}")
                else:
                    print(f"{t} Sharpe: n/a")
        elif choice == "6":
            for t in tickers:
                rsi = compute_rsi(t)
                if rsi is None or rsi.empty:
                    print(f"{t} RSI: n/a")
                    continue
                print(f"{t} RSI: {float(rsi.iloc[-1]):.1f}")
                fig, ax = plt.subplots(figsize=(10, 4))
                ax.plot(rsi.index, rsi.values, color="#F39C12", label="RSI (14)")
                ax.axhline(70, color="#E74C3C", linestyle="--", linewidth=1, label="Overbought (70)")
                ax.axhline(30, color="#3498DB", linestyle="--", linewidth=1, label="Oversold (30)")
                ax.set_title(f"{t} RSI (14)")
                ax.set_xlabel("Date")
                ax.set_ylabel("RSI")
                ax.set_ylim(0, 100)
                ax.grid(True, alpha=0.3)
                ax.legend(loc="upper left")
                fig.tight_layout()
                _save_figure(fig, out_dir, f"{t}_rsi.png")
        elif choice == "7":
            for t in tickers:
                m = compute_macd(t)
                if m is None or m.empty:
                    print(f"{t} MACD: n/a")
                    continue
                fig, ax = plt.subplots(figsize=(10, 4))
                ax.plot(m.index, m["MACD"], label="MACD", color="#1F77B4")
                ax.plot(m.index, m["Signal"], label="Signal", color="#FF7F0E")
                ax.bar(m.index, m["Histogram"], label="Histogram", color="#95A5A6", alpha=0.4)
                ax.axhline(0, color="#666666", linewidth=1)
                ax.set_title(f"{t} MACD (12, 26, 9)")
                ax.set_xlabel("Date")
                ax.set_ylabel("Value")
                ax.grid(True, alpha=0.3)
                ax.legend(loc="upper left")
                fig.tight_layout()
                _save_figure(fig, out_dir, f"{t}_macd.png")
        elif choice == "8":
            return
        else:
            print("Invalid option.")


def _ai_recommendations(df):
    tickers = [
        t
        for t in df["Ticker"].astype(str).str.strip().unique().tolist()
        if t and str(t).lower() != "nan"
    ]
    if not tickers:
        print("No tickers found for recommendations.")
        return

    print("\nAI Recommendations (metrics only; not advice)")
    vol_map = {}
    pe_map = {}
    beta_map = {}
    sharpe_map = {}
    macd_map = {}

    for t in tickers:
        ph, _ = get_history(t)
        if ph is not None and not ph.empty:
            vv = compute_volatility_from_price_history(ph)
            if vv is not None:
                vol_map[t] = vv

        pe = compute_pe_ratio(t)
        if pd.notna(pe) and pe > 0:
            pe_map[t] = float(pe)

        b = beta_values(t)
        if pd.notna(b):
            beta_map[t] = float(b)

        s = compute_sharpe_ratio(t)
        if s is not None:
            sharpe_map[t] = s

        m = compute_macd(t)
        if m is not None and not m.empty:
            last = m.iloc[-1]
            mv = float(last["MACD"])
            sv = float(last["Signal"])
            if mv > sv:
                tag = "Bullish"
            elif mv < sv:
                tag = "Bearish"
            else:
                tag = "Neutral"
            macd_map[t] = (mv, sv, tag)

    print("\nLatest volatility (% annualized)")
    if vol_map:
        for t in tickers:
            if t in vol_map:
                print(f"- {t}: {vol_map[t]:.1f}%")
    else:
        print("No volatility figures computed.")

    print("\nTrailing P/E (positive EPS only)")
    for t in tickers:
        if t in pe_map:
            print(f"- {t}: {pe_map[t]:.2f}")
        else:
            print(f"- {t}: n/a")

    print("\nBeta")
    for t in tickers:
        if t in beta_map:
            print(f"- {t}: {beta_map[t]:.2f}")
        else:
            print(f"- {t}: n/a")

    print("\nSharpe ratio")
    for t in tickers:
        if t in sharpe_map:
            print(f"- {t}: {sharpe_map[t]:.2f}")
        else:
            print(f"- {t}: n/a")

    print("\nMACD crossover")
    if macd_map:
        for t in tickers:
            if t in macd_map:
                mv, sv, tag = macd_map[t]
                print(f"- {t}: MACD {mv:.2f}, Signal {sv:.2f}, {tag}")
    else:
        print("No MACD data computed.")


def _investment_possibilities(state):
    print("\nInvestment possibilities")
    raw = _prompt("Enter new tickers (comma-separated)")
    if raw:
        raw_symbols = [s.strip().upper() for s in raw.replace(";", ",").split(",")]
        seen = set()
        symbols = []
        for s in raw_symbols:
            if not s:
                continue
            s = _IDEA_TICKER_ALIASES.get(s, s)
            if s not in seen:
                seen.add(s)
                symbols.append(s)

        added = []
        invalid = []
        for sym in symbols:
            if sym in state["idea_tickers"]:
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
                state["idea_tickers"].append(sym)
                added.append(sym)
            else:
                invalid.append(sym)

        if added:
            print("Added: " + ", ".join(added))
        if invalid:
            print("Ticker not found or unavailable: " + ", ".join(invalid))

    if not state["idea_tickers"]:
        print("No ticker ideas saved yet.")
        _prompt("Press Enter to return to main menu")
        return

    sess = _yahoo_session()
    print("\nPortfolio and new instruments analysis")
    for idx, sym in enumerate(state["idea_tickers"], start=1):
        ph, info = get_history(sym, session=sess)
        if ph is None or ph.empty or "Close" not in ph.columns:
            print(f"- {sym}: not enough history for assessment.")
            continue
        print(format_new_instrument_assessment(sym, ph, info, item_index=idx))
        if idx < len(state["idea_tickers"]):
            print("-" * 60)

    idea_prices = get_prices_batch(state["idea_tickers"], session=sess)
    if not idea_prices:
        idea_prices = get_prices_via_chart_api(state["idea_tickers"], session=sess)

    print("\nLatest prices (native currency)")
    if idea_prices:
        for sym in state["idea_tickers"]:
            if sym in idea_prices:
                print(f"- {sym}: {idea_prices[sym]:.2f}")
            else:
                print(f"- {sym}: price unavailable")
    else:
        print("Prices unavailable right now.")

    _prompt("Press Enter to return to main menu")


def _alpaca_trading_menu(df):
    print("\nAlpaca trading bot")
    print("This will prompt for paper/live mode and run only during market hours.")
    print("The bot stays active in this tab; it sleeps when market is closed and wakes when open.")
    confirm = _prompt("Start Alpaca bot now? (y/n)", "n").strip().lower()
    if confirm != "y":
        return

    while True:
        try:
            from alpaca_trading_bot import run_bot
        except Exception as exc:
            err_txt = str(exc)
            print(f"Could not load alpaca bot: {err_txt}")
            if "No module named 'alpaca'" in err_txt or 'No module named "alpaca"' in err_txt:
                print("alpaca-py is missing in this Python environment. Installing now...")
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "alpaca-py"])
                    print("alpaca-py installed. Retrying bot load...")
                    continue
                except Exception as install_exc:
                    print(f"Auto-install failed: {install_exc}")
                    print("Run manually: python -m pip install alpaca-py")
            else:
                print("Install dependencies first: python -m pip install -r requirements.txt")

            cmd = _prompt("Type BACK to return to main menu, or press Enter to retry", "").strip().upper()
            if cmd == "BACK":
                return
            continue

        print("Starting Alpaca bot... use Ctrl+C then type EXIT if you truly want to leave bot mode.")
        try:
            tickers = [
                t
                for t in df["Ticker"].astype(str).str.strip().unique().tolist()
                if t and str(t).lower() != "nan"
            ]
            run_bot(portfolio_tickers=tickers)
        except KeyboardInterrupt:
            # run_bot already handles Ctrl+C, but keep this as a safe fallback.
            pass
        except Exception as exc:
            print(f"Alpaca bot error: {exc}")

        cmd = _prompt(
            "Bot session ended. Type BACK to return to main menu, or press Enter to restart bot",
            "",
        ).strip().upper()
        if cmd == "BACK":
            return


def _alpaca_optimizer_menu(df):
    print("\nNasdaq strategy optimization (Alpaca)")
    print("Runs optimization, then can execute the latest optimized signal as a real/paper Alpaca trade.")

    script_path = Path(__file__).resolve().parent / "import files" / "optimize_nasdaq_for_alpaca.py"
    if not script_path.exists():
        print(f"Optimizer script not found: {script_path}")
        _prompt("Press Enter to return to main menu")
        return

    def _unique_clean_symbols(items):
        seen = set()
        out = []
        for raw in items:
            s = str(raw).strip().upper()
            if not s:
                continue
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    def _rank_optimizer_candidates(symbols, lookback_period="180d"):
        rows = []
        for sym in _unique_clean_symbols(symbols):
            try:
                hist, _ = get_history(sym, period=lookback_period, interval="1d")
            except Exception:
                hist = None
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue

            d = hist.sort_index().copy()
            close = pd.to_numeric(d["Close"], errors="coerce").dropna()
            if close.shape[0] < 90:
                continue

            ret_1d = close.pct_change().dropna()
            if ret_1d.empty:
                continue

            ret_3m = float(close.iloc[-1] / close.iloc[max(0, len(close) - 63)] - 1.0)
            ret_1m = float(close.iloc[-1] / close.iloc[max(0, len(close) - 21)] - 1.0)
            vol_ann = float(ret_1d.std() * np.sqrt(252))
            sharpe_approx = float((ret_1d.mean() / ret_1d.std()) * np.sqrt(252)) if ret_1d.std() > 0 else np.nan

            if "Volume" in d.columns:
                vol = pd.to_numeric(d["Volume"], errors="coerce").fillna(0.0)
                dollar_vol = float((close.reindex(vol.index).ffill() * vol).tail(20).mean())
            else:
                dollar_vol = np.nan

            rows.append(
                {
                    "symbol": sym,
                    "ret_3m": ret_3m,
                    "ret_1m": ret_1m,
                    "sharpe": sharpe_approx,
                    "vol_ann": vol_ann,
                    "dollar_vol": dollar_vol,
                }
            )

        if not rows:
            return pd.DataFrame()

        rank_df = pd.DataFrame(rows)
        rank_df = rank_df.replace([np.inf, -np.inf], np.nan).dropna(subset=["ret_3m", "ret_1m", "vol_ann"])
        if rank_df.empty:
            return rank_df

        # Composite ranking:
        # + medium-term momentum (3m)
        # + short-term momentum (1m)
        # + Sharpe approximation
        # + liquidity (dollar volume)
        # - volatility penalty
        rank_df["score"] = (
            0.35 * rank_df["ret_3m"].rank(pct=True)
            + 0.25 * rank_df["ret_1m"].rank(pct=True)
            + 0.20 * rank_df["sharpe"].rank(pct=True)
            + 0.15 * rank_df["dollar_vol"].rank(pct=True)
            + 0.05 * (1.0 - rank_df["vol_ann"].rank(pct=True))
        )
        return rank_df.sort_values("score", ascending=False).reset_index(drop=True)

    while True:
        tech_presets = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "QQQ"]
        continuous_mode = False
        print("\nSymbol source")
        print("  1. Tech presets (NVDA/AAPL/MSFT/AMZN/GOOGL/META/TSLA/QQQ)")
        print("  2. Defense stock universe (curated)")
        print("  3. Portfolio tickers from loaded CSV")
        print("  4. Custom comma-separated tickers")
        print(" 10. ALL sources at once (1 + 2 + 3 + optional 4 custom)")
        source_choice = _prompt_int("Choose source", 1)

        if source_choice == 2:
            base_symbols = list(_DEFENSE_UNIVERSE)
            print(f"Using defense universe ({len(base_symbols)} symbols).")
        elif source_choice == 3:
            base_symbols = [
                t
                for t in df["Ticker"].astype(str).str.strip().unique().tolist()
                if t and str(t).lower() != "nan"
            ]
            if not base_symbols:
                print("No portfolio tickers available; using tech presets instead.")
                base_symbols = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "QQQ"]
        elif source_choice == 4:
            raw = _prompt("Enter tickers (comma-separated)", "NVDA,AAPL,MSFT") or "NVDA,AAPL,MSFT"
            base_symbols = [s.strip().upper() for s in raw.replace(";", ",").split(",") if s.strip()]
        elif source_choice == 10:
            continuous_mode = True
            portfolio_symbols = [
                t
                for t in df["Ticker"].astype(str).str.strip().unique().tolist()
                if t and str(t).lower() != "nan"
            ]
            custom_raw = (_prompt("Optional custom tickers to include (comma-separated, blank to skip)", "") or "").strip()
            custom_symbols = [s.strip().upper() for s in custom_raw.replace(";", ",").split(",") if s.strip()]
            base_symbols = tech_presets + list(_DEFENSE_UNIVERSE) + portfolio_symbols + custom_symbols
            print(
                "Using ALL symbol sources: "
                f"tech={len(tech_presets)}, defense={len(_DEFENSE_UNIVERSE)}, "
                f"portfolio={len(portfolio_symbols)}, custom={len(custom_symbols)}"
            )
        else:
            base_symbols = list(tech_presets)

        base_symbols = _unique_clean_symbols(base_symbols)
        if not base_symbols:
            print("No valid symbols selected.")
            continue

        print(f"Candidate symbols: {', '.join(base_symbols)}")

        use_ranking = ((_prompt("Rank and auto-pick best symbols? (y/n)", "y") or "y").strip().lower() == "y")
        if use_ranking:
            top_n = max(1, _prompt_int("How many symbols to optimize this run", 10))
            rank_df = _rank_optimizer_candidates(base_symbols)
            if rank_df.empty:
                print("Ranking failed (insufficient data). Falling back to input order.")
                symbols = base_symbols[:top_n]
            else:
                symbols = rank_df["symbol"].head(top_n).tolist()
                print("\nTop ranked symbols for optimization:")
                show_cols = ["symbol", "score", "ret_3m", "ret_1m", "sharpe", "vol_ann", "dollar_vol"]
                print(rank_df[show_cols].head(top_n).to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
        else:
            top_n = max(1, _prompt_int("How many symbols to optimize from this list", min(10, len(base_symbols))))
            symbols = base_symbols[:top_n]

        if not symbols:
            print("No symbols selected after filtering.")
            continue

        print(f"\nWill optimize {len(symbols)} symbol(s): {', '.join(symbols)}")

        mode = (_prompt("Alpaca mode (paper/live)", "paper") or "paper").strip().lower()
        if mode not in {"paper", "live"}:
            mode = "paper"
        interval = (_prompt("Bar interval", "1h") or "1h").strip()
        period = (_prompt("History period", "730d") or "730d").strip()
        min_trades = _prompt_int("Minimum train trades", 6)
        cost_bps = _prompt_float("Trading cost (bps)", 2.0)

        do_execute = (_prompt("Execute optimized signal on Alpaca? (y/n)", "y") or "y").strip().lower() == "y"
        order_qty = 1
        allow_short = False
        min_aligned = 2
        strict_trend_alignment = False
        loss_close_threshold = 0.0
        risk_check_seconds = 15
        force_close_eod = False
        eod_close_minutes = 10
        max_pe_ratio = 45.0
        max_volatility_pct = 65.0
        min_companion_bull_votes = 2
        if do_execute:
            order_qty = max(1, _prompt_int("Order quantity", 1))
            allow_short = ((_prompt("Allow short entries on bearish signal? (y/n)", "n") or "n").strip().lower() == "y")
            min_aligned = max(1, _prompt_int("Minimum aligned signals to trade (optimizer+MA+RSI+MACD)", 2))
            max_pe_ratio = _prompt_float("Max trailing P/E allowed before BUY", 45.0)
            max_volatility_pct = _prompt_float("Max annualized volatility % allowed before BUY", 65.0)
            min_companion_bull_votes = max(1, _prompt_int("Min bullish companion votes (MA/RSI/MACD) before BUY", 2))

            if source_choice == 10:
                # Option 10 is the strict "run everything" mode.
                strict_trend_alignment = True
                min_aligned = max(4, int(min_aligned))
                min_companion_bull_votes = max(3, int(min_companion_bull_votes))
                print(
                    "Strict alignment enabled for option 10: "
                    "BUY requires optimizer+MA+RSI+MACD all bullish plus "
                    "Supertrend+Chandelier+Trend Filter bullish."
                )

            loss_close_threshold = _prompt_float(
                "Close open position when unrealized P/L drops below (default 0 = any loss)",
                0.0,
            )
            risk_check_seconds = max(5, _prompt_int("Risk check interval in seconds", 15))
            if source_choice == 10:
                force_close_eod = True
                print("Option 10 enforces end-of-day position close.")
                eod_close_minutes = max(0, _prompt_int("Force-close how many minutes before market close", 10))
            else:
                force_close_eod = ((_prompt("Force-close open position near end of day? (y/n)", "y") or "y").strip().lower() == "y")
                if force_close_eod:
                    eod_close_minutes = max(0, _prompt_int("Force-close how many minutes before market close", 10))

        rerun_minutes = _prompt_float("Auto-rerun every N minutes (0 = no auto-rerun)", 0.0)
        if rerun_minutes < 0:
            rerun_minutes = 0.0
        if continuous_mode and rerun_minutes <= 0:
            rerun_minutes = 5.0
            print("Option 10 continuous mode: auto-rerun forced to every 5 minutes.")
        if source_choice == 10:
            wait_for_open = True
            print("Option 10 enforces market-open check: optimizer will wait for market open before running.")
        else:
            wait_for_open = ((_prompt("If market is closed, wait and run at market open? (y/n)", "y") or "y").strip().lower() == "y")

        cmd_base = [
            sys.executable,
            str(script_path),
            "--mode",
            mode,
            "--interval",
            interval,
            "--period",
            period,
            "--min-trades",
            str(max(0, int(min_trades))),
            "--cost-bps",
            str(max(0.0, float(cost_bps))),
        ]

        if do_execute:
            cmd_base.extend([
                "--execute-trade",
                "--order-qty",
                str(order_qty),
                "--min-aligned-signals",
                str(min_aligned),
                "--loss-close-threshold",
                str(float(loss_close_threshold)),
                "--risk-check-seconds",
                str(max(5, int(risk_check_seconds))),
                "--max-pe-ratio",
                str(max(0.0, float(max_pe_ratio))),
                "--max-volatility-pct",
                str(max(0.0, float(max_volatility_pct))),
                "--min-companion-bull-votes",
                str(max(1, int(min_companion_bull_votes))),
            ])
            if allow_short:
                cmd_base.append("--allow-short-entries")
            if strict_trend_alignment:
                cmd_base.append("--strict-trend-alignment")
            if force_close_eod:
                cmd_base.extend([
                    "--force-close-eod",
                    "--eod-close-minutes",
                    str(max(0, int(eod_close_minutes))),
                ])
        if wait_for_open:
            cmd_base.append("--wait-for-open")

        while True:
            print("\nRunning optimizer batch...")
            passed = []
            failed = []
            for idx, symbol in enumerate(symbols, start=1):
                cmd = list(cmd_base) + ["--symbol", symbol]
                print(f"\n[{idx}/{len(symbols)}] Optimizing {symbol} ...")
                try:
                    subprocess.run(cmd, check=True)
                    passed.append(symbol)
                except subprocess.CalledProcessError as exc:
                    print(f"Optimizer failed for {symbol} (exit code {exc.returncode}).")
                    failed.append(symbol)
                except Exception as exc:
                    print(f"Could not run optimizer for {symbol}: {exc}")
                    failed.append(symbol)

            print("\nBatch summary:")
            print(f"  Success: {len(passed)}")
            if passed:
                print(f"  Symbols succeeded: {', '.join(passed)}")
            print(f"  Failed: {len(failed)}")
            if failed:
                print(f"  Symbols failed: {', '.join(failed)}")

            if rerun_minutes <= 0:
                if continuous_mode:
                    rerun_minutes = 5.0
                    print("Continuous mode active: rerunning in 5.00 minute(s). Press Ctrl+C to stop.")
                    try:
                        time.sleep(300)
                    except KeyboardInterrupt:
                        print("\nAuto-rerun stopped.")
                        follow_up = (
                            _prompt("Type BACK to return to main menu, or press Enter to change optimizer settings", "")
                            or ""
                        ).strip().upper()
                        if follow_up == "BACK":
                            return
                        break
                    continue
                follow_up = (
                    _prompt("Type BACK to return to main menu, press Enter to run optimizer again, or NEW to change settings", "")
                    or ""
                ).strip().upper()
                if follow_up == "BACK":
                    return
                if follow_up == "NEW":
                    break
                continue

            print(
                f"Auto-rerun enabled: next run in {rerun_minutes:.2f} minute(s). "
                "Press Ctrl+C to stop auto-rerun."
            )
            try:
                time.sleep(max(1.0, rerun_minutes * 60.0))
            except KeyboardInterrupt:
                print("\nAuto-rerun stopped.")
                follow_up = (
                    _prompt("Type BACK to return to main menu, or press Enter to change optimizer settings", "")
                    or ""
                ).strip().upper()
                if follow_up == "BACK":
                    return
                break


def main():
    print("Stock Analysis CLI")
    df = None
    state = {"idea_tickers": ["SXR8.DE", "NVDA"]}

    while df is None:
        default_csv = "assets 2025-07-31.csv"
        path = _prompt("CSV file path", default_csv)
        df = _load_csv(path)

    while True:
        print("\nMain menu")
        print("  1. Load current prices and show gains")
        print("  2. Update existing holding")
        print("  3. Add new holding")
        print("  4. Export CSV")
        print("  5. Analysis")
        print("  6. AI Recommendations")
        print("  7. Investment Possibilities")
        print("  8. Alpaca Trading Bot")
        print("  9. Nasdaq Strategy Optimization (Alpaca)")
        print(" 10. Exit")
        choice = _prompt("Select option")

        if choice == "1":
            df = _load_prices(df)
            _print_gains(df)
        elif choice == "2":
            df = _update_asset(df)
        elif choice == "3":
            df = _add_asset(df)
        elif choice == "4":
            today = datetime.now().strftime("%Y-%m-%d")
            _export_csv(df, f"assets_{today}.csv")
        elif choice == "5":
            _analysis_menu(df)
        elif choice == "6":
            _ai_recommendations(df)
        elif choice == "7":
            _investment_possibilities(state)
        elif choice == "8":
            _alpaca_trading_menu(df)
        elif choice == "9":
            _alpaca_optimizer_menu(df)
        elif choice == "10":
            print("Goodbye.")
            break
        else:
            print("Invalid option.")


if __name__ == "__main__":
    main()
