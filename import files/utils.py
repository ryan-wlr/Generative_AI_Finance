
import os
import time
import pandas as pd
import yfinance as yf
import numpy as np
import requests
import matplotlib.pyplot as plt
import langchain_openai
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate

# Yahoo often blocks requests without a browser-like User-Agent
def _yahoo_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json,*/*;q=0.9",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s

# Throttle: avoid rate limits when fetching many tickers (reduced for faster load; app caches results)
_REQUEST_DELAY = 0.2

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1mo"
# Daily bars for ~1y+ of trading days (needed for MA200 when yfinance is empty)
CHART_HISTORY_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    "?interval=1d&range=2y&includePrePost=false"
)


def history_from_yahoo_chart_api(session, symbol: str):
    """
    Build a price DataFrame (DatetimeIndex, Close) from Yahoo's chart endpoint.
    Same session/headers as spot prices — works when yfinance returns empty.
    """
    symbol = str(symbol).strip()
    if not symbol:
        return None
    url = CHART_HISTORY_URL.format(ticker=requests.utils.quote(symbol))
    try:
        time.sleep(_REQUEST_DELAY)
        r = session.get(url, timeout=25)
        r.raise_for_status()
        payload = r.json()
        result = payload.get("chart", {}).get("result")
        if not result:
            return None
        res0 = result[0]
        ts = res0.get("timestamp") or []
        quotes = (res0.get("indicators") or {}).get("quote") or [{}]
        q0 = quotes[0] if quotes else {}
        closes = q0.get("close") or []
        if not ts or not closes:
            return None
        n = min(len(ts), len(closes))
        if n < 1:
            return None
        ts, closes = ts[:n], closes[:n]
        idx = pd.to_datetime(ts, unit="s")
        df = pd.DataFrame({"Close": closes}, index=idx)
        df = df.loc[pd.notna(df["Close"]) & (df["Close"] > 0)]
        if df.empty:
            return None
        return df.sort_index()
    except Exception:
        return None


def _price_from_yahoo_chart_api(session, symbol: str):
    """
    Fetch last/current price by calling Yahoo's chart API directly (no yfinance).
    Returns float price or np.nan. Works when yfinance returns empty (e.g. blocked requests).
    """
    symbol = str(symbol).strip()
    if not symbol:
        return np.nan
    url = CHART_URL.format(ticker=requests.utils.quote(symbol))
    try:
        time.sleep(_REQUEST_DELAY)
        r = session.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return np.nan
        res0 = result[0]
        meta = res0.get("meta", {})
        for key in ("regularMarketPrice", "previousClose", "chartPreviousClose"):
            v = meta.get(key)
            if v is not None and isinstance(v, (int, float)) and v > 0:
                return float(v)
        quote = res0.get("indicators", {}).get("quote", [{}])[0]
        closes = quote.get("close") or []
        for v in reversed(closes):
            if v is not None and isinstance(v, (int, float)) and v > 0:
                return float(v)
        return np.nan
    except Exception:
        return np.nan


def get_prices_via_chart_api(tickers: list, session=None) -> dict:
    """
    Fetch last price for each ticker using Yahoo Chart API (no yfinance).
    Returns dict ticker -> price. Use when yfinance returns nothing.
    """
    out = {}
    sess = session or _yahoo_session()
    for t in tickers:
        t = str(t).strip()
        if not t or pd.isna(t):
            continue
        p = _price_from_yahoo_chart_api(sess, t)
        if pd.notna(p) and p > 0:
            out[t] = float(p)
    return out


def _last_close(ticker, periods=("5d", "1mo")):
    """Get most recent price via yfinance: history, then fast_info, then info."""
    for period in periods:
        try:
            time.sleep(_REQUEST_DELAY)
            hist = ticker.history(period=period)
            if hist is not None and not hist.empty and "Close" in hist.columns:
                last = hist["Close"].iloc[-1]
                if pd.notna(last) and last > 0:
                    return float(last)
        except Exception:
            continue
    # 2) Fallback: fast_info.last_price (works when history is empty)
    try:
        time.sleep(_REQUEST_DELAY)
        fast = getattr(ticker, "fast_info", None)
        if fast is not None:
            lp = getattr(fast, "last_price", None)
            if lp is not None and pd.notna(lp) and lp > 0:
                return float(lp)
    except Exception:
        pass
    # 3) Fallback: info['regularMarketPrice']
    try:
        time.sleep(_REQUEST_DELAY)
        info = ticker.info
        if isinstance(info, dict):
            for key in ("regularMarketPrice", "previousClose", "open"):
                val = info.get(key)
                if val is not None and pd.notna(val) and val > 0:
                    return float(val)
    except Exception:
        pass
    return np.nan
        
        

def get_fx_rate(from_currency, to_currency: str = "EUR", session=None) -> float:
    """
    Get the FX rate from Yahoo (to_currency per 1 from_currency). Returns 1.0 if same currency.
    Tries Chart API first (direct HTTP), then yfinance.
    """
    if from_currency == to_currency:
        return 1.0
    pair = f"{from_currency}{to_currency}=X"
    sess = session or _yahoo_session()
    rate = _price_from_yahoo_chart_api(sess, pair)
    if pd.notna(rate) and rate > 0:
        return float(rate)
    try:
        rate = _last_close(yf.Ticker(pair))
        return rate if pd.notna(rate) and rate > 0 else np.nan
    except Exception:
        return np.nan


def get_prices_batch(tickers: list, session=None) -> dict:
    """
    Fetch last close for multiple tickers in one request. Returns dict ticker -> price (native).
    """
    if not tickers:
        return {}
    tickers = [str(t).strip() for t in tickers if pd.notna(t) and str(t).strip()]
    if not tickers:
        return {}
    try:
        time.sleep(_REQUEST_DELAY)
        data = yf.download(
            tickers,
            period="1mo",
            progress=False,
            auto_adjust=True,
            group_by="column",
            threads=False,
            timeout=15,
        )
        out = {}
        if data.empty:
            return out
        # Single ticker: columns are Open, High, Low, Close, ...
        if len(tickers) == 1:
            if "Close" in data.columns:
                last = data["Close"].iloc[-1]
                if pd.notna(last) and last > 0:
                    out[tickers[0]] = float(last)
            return out
        # Multiple: group_by='column' gives data['Close'] with columns = tickers
        try:
            if "Close" not in data.columns and isinstance(data.columns, pd.MultiIndex):
                if "Close" in data.columns.get_level_values(0):
                    close_df = data["Close"]
                else:
                    return out
            else:
                close_df = data["Close"] if "Close" in data.columns else None
            if close_df is None or close_df.empty:
                return out
            last_row = close_df.iloc[-1]
            for t in tickers:
                if t in last_row.index:
                    val = last_row[t]
                    if pd.notna(val) and val > 0:
                        out[t] = float(val)
        except Exception:
            pass
        return out
    except Exception:
        return {}


def get_price_local(row, fx_cache: dict, session=None) -> float:
    """
    Fetch the Yahoo price in native currency and convert to EUR using fx_cache.
    Tries Chart API first (direct HTTP), then yfinance.
    """
    try:
        sess = session or _yahoo_session()
        sym = str(row["Ticker"]).strip()
        price_native = _price_from_yahoo_chart_api(sess, sym)
        if pd.isna(price_native) or price_native <= 0:
            price_native = _last_close(yf.Ticker(sym))
        if pd.isna(price_native) or price_native <= 0:
            return np.nan
        rate = fx_cache.get(row["Currency Yahoo"], np.nan)
        if pd.isna(rate) or rate <= 0:
            return np.nan
        return price_native * rate
    except Exception:
        return np.nan

# Build a function that retrives prices and info
def get_history(ticker, period="1y", interval="1d", session=None):
    """
    Fetch historical data for a ticker.
    yfinance must use its default HTTP client (do not pass requests.Session — unsupported).
    If history is empty or errors, falls back to Yahoo Chart API (browser-like requests session).
    """
    sess = session or _yahoo_session()
    sym = str(ticker).strip()
    if not sym:
        return None, None
    info = {}
    try:
        t = yf.Ticker(sym)
        time.sleep(_REQUEST_DELAY)
        price_history = t.history(period=period, interval=interval, timeout=20)
        if (
            price_history is not None
            and not price_history.empty
            and "Close" in price_history.columns
            and pd.notna(price_history["Close"].iloc[-1])
            and float(price_history["Close"].iloc[-1]) > 0
        ):
            try:
                raw = t.info
                info = raw if isinstance(raw, dict) else {}
            except Exception:
                pass
            return price_history, info
    except Exception as e:
        print(f"[WARN] yfinance history failed for {sym}: {e}")

    df = history_from_yahoo_chart_api(sess, sym)
    if df is not None and not df.empty:
        return df, info
    print(f"[WARN] No usable history for {sym} (yfinance empty; chart API returned nothing).")
    return None, None


def latest_vs_ma_label(latest_price, ma_val):
    """Latest close vs MA: Above if price > MA, Below if price < MA."""
    if not pd.notna(latest_price) or not pd.notna(ma_val):
        return "n/a"
    if latest_price > ma_val:
        return "Above"
    if latest_price < ma_val:
        return "Below"
    return "Equal"


def compute_moving_averages(ticker):
    """
    Compute moving averages for a ticker
    """
    try:
        price_history, info = get_history(ticker)
        if price_history is None or price_history.empty or "Close" not in price_history.columns:
            return None, None
        price_history["MA50"] = price_history["Close"].rolling(50).mean()
        price_history["MA100"] = price_history["Close"].rolling(100).mean()
        price_history["MA200"] = price_history["Close"].rolling(200).mean()

        latest = {
            "latest_price": float(price_history["Close"].iloc[-1]) if pd.notna(price_history["Close"].iloc[-1]) else np.nan,
            "ma50": float(price_history["MA50"].iloc[-1]) if pd.notna(price_history["MA50"].iloc[-1]) else np.nan,
            "ma100": float(price_history["MA100"].iloc[-1]) if pd.notna(price_history["MA100"].iloc[-1]) else np.nan,
            "ma200": float(price_history["MA200"].iloc[-1]) if pd.notna(price_history["MA200"].iloc[-1]) else np.nan,
        }
        latest_price = latest["latest_price"]
        ma50 = latest["ma50"]
        ma100 = latest["ma100"]
        ma200 = latest["ma200"]
        # Terminal log (ASCII only — Windows consoles often use cp1252 and choke on emoji)
        _tag_mark = {"Above": "^", "Below": "v", "Equal": "=", "n/a": "?"}
        print(f"\n[MA] {ticker} - spot vs moving averages")
        lp_txt = f"{latest_price:.1f}" if pd.notna(latest_price) else "n/a"
        print(f"  Latest: {lp_txt}")
        for ma_label, ma_val in (("MA50", ma50), ("MA100", ma100), ("MA200", ma200)):
            tag = latest_vs_ma_label(latest_price, ma_val)
            mk = _tag_mark.get(tag, "")
            if pd.notna(ma_val):
                print(f"  {ma_label}: {ma_val:.1f} ({tag}) {mk}")
            else:
                print(f"  {ma_label}: n/a ({tag}) {mk}")
        return price_history, latest
    except Exception as e:
        # Keep utility Streamlit-friendly by returning status instead of printing to terminal.
        return None, None

def plot_moving_averages(price_history, ticker):
    """
    Build a matplotlib figure for moving averages.
    The caller can render it with st.pyplot(fig) in Streamlit.
    """
    if price_history is None or price_history.empty:
        return None
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(price_history["Close"], label="Close")
    ax.plot(price_history["MA50"], label="MA50")
    ax.plot(price_history["MA100"], label="MA100")
    ax.plot(price_history["MA200"], label="MA200")

    # Customize the plot
    ax.set_title(f"{ticker} - Moving Average vs Price")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price")
    ax.grid(True)
    ax.legend()
    fig.tight_layout()
    return fig


def _rolling_annualized_vol_series(price_history, window=250):
    """
    Daily returns -> rolling annualized volatility (%), sqrt(250) scaling.
    Returns (series, window_used) or (None, None).
    """
    if price_history is None or price_history.empty or "Close" not in price_history.columns:
        return None, None
    returns = price_history["Close"].pct_change().dropna()
    if len(returns) < 5:
        return None, None
    w = min(window, max(5, len(returns) - 1))
    rolling = returns.rolling(window=w).std() * np.sqrt(250) * 100
    return rolling, w


def compute_volatility_from_price_history(price_history):
    """Latest rolling annualized volatility (%) from a Close series; None if unavailable."""
    rolling, _ = _rolling_annualized_vol_series(price_history)
    if rolling is None or rolling.empty:
        return None
    v = rolling.iloc[-1]
    if pd.isna(v):
        return None
    return float(v)


def compute_volatility(ticker):
    """Latest rolling annualized volatility (%). None if history is unavailable."""
    price_history, _ = get_history(ticker)
    return compute_volatility_from_price_history(price_history)


def plot_volatility(price_history, ticker):
    """
    Matplotlib figure: rolling annualized volatility over time (%).
    Same convention as compute_volatility; render with st.pyplot(fig) in Streamlit.
    """
    rolling, w = _rolling_annualized_vol_series(price_history)
    if rolling is None or rolling.empty:
        return None
    fig, ax = plt.subplots(figsize=(10, 4))
    rolling.plot(ax=ax, color="steelblue", label=f"Ann. vol % (~{w}d window)")
    ax.set_title(f"{ticker} — rolling volatility (annualized %)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Volatility %")
    ax.grid(True)
    ax.legend(loc="upper right")
    fig.tight_layout()
    return fig


def _first_finite_positive_eps(info):
    """First positive trailing EPS from Yahoo `info`, or None if unknown, False if clearly non-positive."""
    for key in ("trailingEps", "epsTrailingTwelveMonths"):
        v = info.get(key)
        if v is None or not isinstance(v, (int, float)) or not pd.notna(v) or not np.isfinite(v):
            continue
        if v <= 0:
            return False, None
        return True, float(v)
    return None, None


def _price_for_pe(info):
    for key in ("currentPrice", "regularMarketPrice", "regularMarketPreviousClose", "previousClose"):
        v = info.get(key)
        if v is not None and isinstance(v, (int, float)) and pd.notna(v) and np.isfinite(v) and v > 0:
            return float(v)
    return None


def compute_pe_ratio(ticker):
    """
    Trailing P/E from Yahoo (yfinance .info) for issuers with positive TTM earnings.

    Uses trailing P/E only when trailing EPS is positive (or computable as price/positive EPS).
    Forward P/E is not used here, so a positive forward multiple cannot mask negative trailing earnings.
    Returns np.nan if earnings are negative, missing, or not applicable (ETF/crypto).
    """
    sym = str(ticker).strip()
    if not sym:
        return np.nan
    try:
        time.sleep(_REQUEST_DELAY)
        info = yf.Ticker(sym).info
        if not isinstance(info, dict):
            return np.nan

        earn_ok, eps = _first_finite_positive_eps(info)
        if earn_ok is False:
            return np.nan

        tpe = info.get("trailingPE")
        if earn_ok is True and eps is not None:
            if tpe is not None and isinstance(tpe, (int, float)) and pd.notna(tpe) and np.isfinite(tpe) and tpe > 0:
                return float(tpe)
            price = _price_for_pe(info)
            if price is not None and eps > 0:
                return price / eps
            return np.nan

        # Trailing EPS not reported: only trust Yahoo's trailing P/E if it is a positive finite multiple.
        if tpe is not None and isinstance(tpe, (int, float)) and pd.notna(tpe) and np.isfinite(tpe) and tpe > 0:
            return float(tpe)
        return np.nan
    except Exception:
        pass
    return np.nan


def plot_pe_ratio(df):
    """
    Matplotlib figure: PE ratio bar chart for unique tickers in the holdings DataFrame.
    Render in Streamlit with st.pyplot(fig, use_container_width=True); do not use plt.show().
    Returns (figure_or_none, dict ticker -> pe, list of tickers with no usable P/E for warnings).
    """
    if df is None or df.empty or "Ticker" not in df.columns:
        return None, {}, []
    pe_ratios = {}
    missing = []
    for ticker in df["Ticker"].astype(str).str.strip().unique():
        if not ticker or ticker.lower() == "nan":
            continue
        pe_ratio = compute_pe_ratio(ticker)
        if pd.notna(pe_ratio) and pe_ratio > 0:
            pe_ratios[ticker] = pe_ratio
        else:
            missing.append(ticker)
    if not pe_ratios:
        return None, {}, missing
    fig, ax = plt.subplots(figsize=(10, 5))
    tickers_ord = list(pe_ratios.keys())
    vals = [pe_ratios[t] for t in tickers_ord]
    x = np.arange(len(tickers_ord))
    ax.bar(x, vals, color="#E74C3C", edgecolor="white", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(tickers_ord, rotation=45, ha="right")
    ax.set_title("Portfolio Tickers PE Ratio")
    ax.set_xlabel("Ticker")
    ax.set_ylabel("PE Ratio")
    ymax = max(vals) * 1.12 if vals else 40.0
    ax.set_ylim(0, max(ymax, 5.0))
    ax.grid(axis="y", color="#d0d0d0", linestyle="-", linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return fig, pe_ratios, missing


def beta_values(ticker):
    """
    Fetch beta from Yahoo Finance info for one ticker.
    Returns float beta or np.nan when unavailable.
    """
    sym = str(ticker).strip()
    if not sym:
        return np.nan
    try:
        time.sleep(_REQUEST_DELAY)
        info = yf.Ticker(sym).info
        if not isinstance(info, dict):
            return np.nan
        v = info.get("beta")
        if v is not None and isinstance(v, (int, float)) and pd.notna(v) and np.isfinite(v):
            return float(v)
    except Exception:
        pass
    return np.nan


def plot_beta(beta_dict):
    """
    Matplotlib figure for beta values by ticker.
    Returns None if there is nothing to plot.
    """
    if not beta_dict:
        return None
    tickers_ord = list(beta_dict.keys())
    vals = [beta_dict[t] for t in tickers_ord]
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(tickers_ord))
    ax.bar(x, vals, color="#9B59B6", edgecolor="white", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(tickers_ord, rotation=45, ha="right")
    ax.set_title("Portfolio Tickers Beta")
    ax.set_xlabel("Ticker")
    ax.set_ylabel("Beta")
    ax.axhline(1.0, color="#666666", linestyle="--", linewidth=1, alpha=0.8)
    ymax = max(vals) * 1.12 if vals else 2.0
    ax.set_ylim(0, max(ymax, 1.2))
    ax.grid(axis="y", color="#d0d0d0", linestyle="-", linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return fig


def compute_sharpe_ratio(ticker, risk_free_rate=0.0):
    """
    Annualized Sharpe ratio from daily returns using ~250 trading days.
    Returns float or None when unavailable.
    """
    price_history, _ = get_history(ticker)
    if price_history is None or price_history.empty or "Close" not in price_history.columns:
        return None
    returns = price_history["Close"].pct_change().dropna()
    if returns.empty:
        return None
    excess = returns - (risk_free_rate / 250.0)
    vol = excess.std()
    if pd.isna(vol) or vol <= 0:
        return None
    sharpe = (excess.mean() / vol) * np.sqrt(250)
    if not pd.notna(sharpe) or not np.isfinite(sharpe):
        return None
    return float(sharpe)


def compute_rsi(ticker, period=14):
    """
    RSI time series from Close prices for a ticker.
    Returns a pandas Series or None.
    """
    price_history, _ = get_history(ticker)
    if price_history is None or price_history.empty or "Close" not in price_history.columns:
        return None
    delta = price_history["Close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.replace([np.inf, -np.inf], np.nan).dropna()
    if rsi.empty:
        return None
    return rsi


def compute_macd(ticker, fast=12, slow=26, signal=9):
    """
    MACD indicators for a ticker.
    Returns DataFrame with columns: MACD, Signal, Histogram or None.
    """
    price_history, _ = get_history(ticker)
    if price_history is None or price_history.empty or "Close" not in price_history.columns:
        return None
    close = price_history["Close"].astype(float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - signal_line
    out = pd.DataFrame(
        {"MACD": macd, "Signal": signal_line, "Histogram": hist},
        index=price_history.index,
    ).dropna()
    if out.empty:
        return None
    return out


def _rsi_series_from_close(close: pd.Series, period: int = 14) -> pd.Series | None:
    """RSI time series from Close (same convention as compute_rsi)."""
    if close is None or close.empty:
        return None
    delta = close.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.replace([np.inf, -np.inf], np.nan).dropna()
    if rsi.empty:
        return None
    return rsi


def _macd_frame_from_close(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame | None:
    """MACD(12,26,9) from Close (same convention as compute_macd)."""
    if close is None or close.empty:
        return None
    c = close.astype(float)
    ema_fast = c.ewm(span=fast, adjust=False).mean()
    ema_slow = c.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - signal_line
    out = pd.DataFrame({"MACD": macd, "Signal": signal_line, "Histogram": hist}).dropna()
    if out.empty:
        return None
    return out


def _annualized_sharpe_from_close(close: pd.Series, risk_free_rate: float = 0.0) -> float | None:
    returns = close.astype(float).pct_change().dropna()
    if returns.empty or len(returns) < 30:
        return None
    excess = returns - (risk_free_rate / 250.0)
    vol = excess.std()
    if pd.isna(vol) or vol <= 0:
        return None
    sharpe = (excess.mean() / vol) * np.sqrt(250)
    if not pd.notna(sharpe) or not np.isfinite(sharpe):
        return None
    return float(sharpe)


def format_new_instrument_assessment(
    ticker: str,
    price_history: pd.DataFrame,
    info: dict | None,
    item_index: int = 1,
) -> str:
    """
    Course-style "New Instruments Assessment" block: numbered title, Strengths, Risks,
    Momentum Signal, Recommendation — from a single price history (+ optional Yahoo info).
    """
    info = info if isinstance(info, dict) else {}
    sym = str(ticker).strip().upper()
    raw_name = (
        info.get("longName")
        or info.get("shortName")
        or info.get("symbol")
        or sym
    )
    company = str(raw_name).replace("\n", " ").replace("*", "").strip() or sym
    if len(company) > 90:
        company = company[:88] + "…"

    close = price_history["Close"].astype(float)
    n = len(close)
    if n < 20:
        return (
            f"**{item_index}. {sym}** ({company})\n\n"
            "*   **Strengths:** Not enough price history in this window to score the setup reliably.\n"
            "*   **Risks:** Data may be incomplete; verify the listing and try again later.\n"
            "*   **Momentum Signal:** Neutral — insufficient history.\n"
            "*   **Recommendation:** No action — wait for a longer history window."
        )

    lp = float(close.iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1]) if n >= 50 else float("nan")
    ma100 = float(close.rolling(100).mean().iloc[-1]) if n >= 100 else float("nan")
    ma200 = float(close.rolling(200).mean().iloc[-1]) if n >= 200 else float("nan")
    mas_valid = []
    for label, mv in (("MA50", ma50), ("MA100", ma100), ("MA200", ma200)):
        if pd.notna(mv) and np.isfinite(mv):
            mas_valid.append((label, mv, lp > mv))
    n_ma = len(mas_valid)
    n_above = sum(1 for *_, above in mas_valid if above)

    if n_ma >= 3 and n_above == 3:
        ma_line = (
            "Price is above all major moving averages (MA50, MA100, MA200), indicating a strong uptrend."
        )
    elif n_ma >= 2 and n_above >= n_ma - 1:
        ma_line = "Price is mostly above key moving averages, suggesting an uptrend."
    elif n_ma >= 1 and n_above == 0:
        ma_line = "Price is below its tracked moving averages, suggesting a weaker or corrective setup."
    elif n_ma == 0:
        ma_line = "Moving averages are not yet available on this history window."
    else:
        ma_line = "Price is mixed relative to MA50, MA100, and MA200."

    sharpe = _annualized_sharpe_from_close(close)
    if sharpe is None:
        sharpe_line = ""
    elif sharpe >= 1.2:
        sharpe_line = (
            f"Very high Sharpe ratio ({sharpe:.2f}), indicating strong risk-adjusted returns on this window."
        )
    elif sharpe >= 0.5:
        sharpe_line = (
            f"Positive Sharpe ratio ({sharpe:.2f}), suggesting reasonable risk-adjusted returns vs. volatility."
        )
    elif sharpe >= 0:
        sharpe_line = (
            f"Modest positive Sharpe ({sharpe:.2f}); returns have been positive vs. volatility but not strong."
        )
    else:
        sharpe_line = (
            f"Negative Sharpe ({sharpe:.2f}), indicating weak risk-adjusted performance over this window."
        )

    vol_pct = compute_volatility_from_price_history(price_history)
    if vol_pct is None:
        vol_line = ""
    elif vol_pct >= 45:
        vol_line = f"Very high realized volatility (~{vol_pct:.0f}% annualized on this measure)."
    elif vol_pct >= 28:
        vol_line = f"Elevated volatility (~{vol_pct:.0f}% annualized)."
    else:
        vol_line = f"Moderate volatility (~{vol_pct:.0f}% annualized)."

    rsi_ser = _rsi_series_from_close(close, 14)
    rsi_last = float(rsi_ser.iloc[-1]) if rsi_ser is not None and not rsi_ser.empty else float("nan")
    if pd.notna(rsi_last) and np.isfinite(rsi_last):
        if rsi_last >= 70:
            rsi_line = f"RSI ({rsi_last:.1f}) is in an overbought zone for many traders."
        elif rsi_last >= 60:
            rsi_line = f"RSI ({rsi_last:.1f}) is elevated but not yet extreme."
        elif rsi_last <= 30:
            rsi_line = f"RSI ({rsi_last:.1f}) is in an oversold zone for many traders."
        else:
            rsi_line = f"RSI ({rsi_last:.1f}) is in a neutral band."
    else:
        rsi_line = ""

    macd_df = _macd_frame_from_close(close)
    macd_bull = None
    macd_line = ""
    if macd_df is not None and not macd_df.empty:
        last = macd_df.iloc[-1]
        mv, sv = float(last["MACD"]), float(last["Signal"])
        macd_bull = mv > sv
        if mv > sv and mv > 0 and sv > 0:
            macd_line = "MACD and signal are positive with MACD above the signal line (bullish momentum)."
        elif mv > sv:
            macd_line = "MACD is above the signal line (bullish crossover / momentum)."
        elif mv < sv:
            macd_line = "MACD is below the signal line (bearish momentum vs. this rule set)."
        else:
            macd_line = "MACD is near the signal line (transition zone)."

    pe = compute_pe_ratio(sym)
    beta = beta_values(sym)
    is_etf = str(info.get("quoteType", "")).upper() == "ETF" or str(info.get("instrumentType", "")).upper() == "ETF"

    pe_line = ""
    if pd.notna(pe) and np.isfinite(pe) and pe > 0:
        if pe >= 45:
            pe_line = f"P/E (~{pe:.0f}) is elevated; growth expectations are embedded in the multiple."
        elif pe >= 25:
            pe_line = f"P/E (~{pe:.0f}) is moderately high vs. many large-cap peers."
        else:
            pe_line = f"Trailing P/E (~{pe:.0f}) is not extreme on this snapshot."
    elif is_etf:
        pe_line = "No meaningful trailing stock-style P/E (typical for a fund/ETF structure)."
    else:
        pe_line = "Trailing P/E is unavailable or not comparable (losses, sparse fundamentals, or non-equity structure)."

    if pd.notna(beta) and np.isfinite(beta):
        if beta >= 1.6:
            beta_line = f"Beta (~{beta:.2f}) indicates high sensitivity to the market proxy Yahoo uses."
        elif beta >= 1.1:
            beta_line = f"Beta (~{beta:.2f}) is above 1, suggesting above-market swing sensitivity."
        elif beta <= 0.85:
            beta_line = f"Beta (~{beta:.2f}) is below 1, suggesting below-market swing sensitivity vs. that proxy."
        else:
            beta_line = f"Beta (~{beta:.2f}) is near market-like sensitivity."
    else:
        beta_line = "Beta is unavailable or not reported for this listing."

    strength_bits = [ma_line]
    if sharpe_line:
        strength_bits.append(sharpe_line)
    if macd_line and macd_bull is True:
        strength_bits.append(macd_line)
    if rsi_line and pd.notna(rsi_last) and rsi_last >= 50:
        strength_bits.append(rsi_line)
    if pe_line and pd.notna(pe) and pe > 0 and pe < 60:
        strength_bits.append(pe_line)
    if beta_line and "unavailable" not in beta_line.lower():
        strength_bits.append(beta_line)
    if vol_line and vol_pct is not None and vol_pct < 35:
        strength_bits.append(vol_line)

    strengths = " ".join(strength_bits) if strength_bits else "Use other tabs for deeper fundamentals; headline metrics are mixed or incomplete."

    risk_bits = []
    if vol_pct is not None and vol_pct >= 35:
        risk_bits.append(vol_line or f"High volatility (~{vol_pct:.0f}%).")
    if pd.notna(pe) and pe >= 40:
        risk_bits.append("Elevated valuation vs. earnings unless growth sustains.")
    if pd.notna(rsi_last) and rsi_last >= 72:
        risk_bits.append("Momentum is stretched (high RSI), which can precede pullbacks.")
    if n_ma >= 2 and n_above <= 1:
        risk_bits.append("Trend structure vs. moving averages is not uniformly strong.")
    if sharpe is not None and sharpe < 0:
        risk_bits.append("Risk-adjusted returns have been weak on this window.")
    if macd_bull is False:
        risk_bits.append("MACD vs. signal is not bullish on the latest bar.")
    risks = " ".join(risk_bits) if risk_bits else "Standard market, liquidity, and single-name risks always apply."

    # Momentum label + recommendation score (simple heuristic)
    score = 0
    if n_ma >= 3 and n_above == 3:
        score += 3
    elif n_ma >= 2 and n_above >= n_ma - 1:
        score += 2
    elif n_above >= 1:
        score += 1
    if macd_bull is True:
        score += 2
    elif macd_bull is False:
        score -= 1
    if sharpe is not None:
        if sharpe >= 1.0:
            score += 2
        elif sharpe >= 0.4:
            score += 1
        elif sharpe < 0:
            score -= 2
    if vol_pct is not None and vol_pct >= 50:
        score -= 2
    elif vol_pct is not None and vol_pct >= 35:
        score -= 1
    if pd.notna(rsi_last):
        if rsi_last >= 78:
            score -= 1
        elif rsi_last <= 35:
            score += 0

    mom_parts = []
    if n_ma >= 3 and n_above == 3:
        mom_parts.append("price above major MAs")
    if sharpe is not None and sharpe >= 1.0:
        mom_parts.append("high Sharpe")
    if macd_bull is True:
        mom_parts.append("positive MACD vs. signal")
    if pd.notna(rsi_last):
        if rsi_last >= 60:
            mom_parts.append("firm RSI")
        elif 40 <= rsi_last < 60:
            mom_parts.append("neutral RSI")

    if score >= 6:
        momentum = "Strong bullish (" + ", ".join(mom_parts) + ")." if mom_parts else "Strong bullish."
        rec = (
            "Buy — momentum and risk-adjusted returns look strong on this window; still **size for volatility** "
            "and your risk budget."
        )
    elif score >= 3:
        momentum = "Bullish / constructive (" + ", ".join(mom_parts) + ")." if mom_parts else "Bullish / constructive."
        rec = (
            "Hold / accumulate cautiously — constructive setup, but confirm fundamentals and position size vs. "
            "volatility."
        )
    elif score >= 1:
        momentum = "Neutral with bullish hints (" + ", ".join(mom_parts) + ")." if mom_parts else "Neutral with bullish hints."
        rec = "Hold — wait for clearer trend confirmation or use smaller sizing if adding."
    else:
        momentum = "Neutral / cautious (" + ", ".join(mom_parts) + ")." if mom_parts else "Neutral / cautious."
        rec = "Caution / reduce sizing — trend and risk-adjusted metrics are not strong on this snapshot."

    return (
        f"**{item_index}. {sym}** ({company})\n\n"
        f"*   **Strengths:** {strengths}\n\n"
        f"*   **Risks:** {risks}\n\n"
        f"*   **Momentum Signal:** {momentum}\n\n"
        f"*   **Recommendation:** {rec}"
    )


PORTFOLIO_AI_SYSTEM_PROMPT = """You are an expert portfolio analyst and personal finance educator.

For every ticker in the current portfolio:
1) Summarize key strengths and risks using the KPIs provided.
2) Flag momentum signals (moving averages, MACD, RSI, Sharpe, volatility).
3) Give a final recommendation (Buy, Sell, Hold) with a 1–2 sentence rationale.

If candidate instruments are provided, assess each relative to the existing portfolio.

You MUST end your response with a section titled exactly:
## Overall Portfolio Note

That section must be 3–5 sentences covering diversification, aggregate risk (volatility/beta),
valuation/momentum themes, and one concrete portfolio-level action.

Format the full answer in markdown and start with a single H1 title."""


def build_portfolio_kpi_dataframe(
    tickers: list,
    *,
    assets: list | None = None,
    prices_today: list | None = None,
    session=None,
) -> pd.DataFrame:
    """Build a KPI table for LLM context (no console output)."""
    sess = session or _yahoo_session()
    rows = []
    for i, raw in enumerate(tickers):
        sym = str(raw).strip().upper()
        if not sym or sym.lower() == "nan":
            continue
        ph, info = get_history(sym, session=sess)
        if ph is None or ph.empty or "Close" not in ph.columns:
            continue
        info = info if isinstance(info, dict) else {}
        close = ph["Close"].astype(float)
        n = len(close)
        ma50 = float(close.rolling(50).mean().iloc[-1]) if n >= 50 else np.nan
        ma100 = float(close.rolling(100).mean().iloc[-1]) if n >= 100 else np.nan
        ma200 = float(close.rolling(200).mean().iloc[-1]) if n >= 200 else np.nan
        vol = compute_volatility_from_price_history(ph)
        pe = compute_pe_ratio(sym)
        beta = beta_values(sym)
        sharpe = _annualized_sharpe_from_close(close)
        rsi_ser = _rsi_series_from_close(close, 14)
        rsi_last = (
            float(rsi_ser.iloc[-1])
            if rsi_ser is not None and not rsi_ser.empty and pd.notna(rsi_ser.iloc[-1])
            else np.nan
        )
        macd_df = _macd_frame_from_close(close)
        macd_val = signal_val = np.nan
        if macd_df is not None and not macd_df.empty:
            last = macd_df.iloc[-1]
            macd_val = float(last["MACD"])
            signal_val = float(last["Signal"])
        if assets and i < len(assets) and assets[i]:
            asset = str(assets[i])
        else:
            asset = (
                info.get("longName")
                or info.get("shortName")
                or info.get("symbol")
                or sym
            )
        if prices_today and i < len(prices_today) and pd.notna(prices_today[i]):
            price = float(prices_today[i])
        else:
            price = float(close.iloc[-1])
        rows.append(
            {
                "Ticker": sym,
                "Asset": asset,
                "Price Today": price,
                "MA50": ma50,
                "MA100": ma100,
                "MA200": ma200,
                "Volatility": vol,
                "PE Ratio": pe,
                "Beta": beta,
                "Sharpe Ratio": sharpe,
                "RSI": rsi_last,
                "MACD": macd_val,
                "Signal": signal_val,
            }
        )
    return pd.DataFrame(rows)


def format_overall_portfolio_note_heuristic(kpi_df: pd.DataFrame) -> str:
    """Rule-based overall portfolio note when the LLM is unavailable."""
    if kpi_df is None or kpi_df.empty:
        return (
            "## Overall Portfolio Note\n\n"
            "Not enough KPI data to summarize the portfolio. Load prices and verify tickers, then try again."
        )
    n = len(kpi_df)
    vols = pd.to_numeric(kpi_df.get("Volatility"), errors="coerce").dropna()
    betas = pd.to_numeric(kpi_df.get("Beta"), errors="coerce").dropna()
    sharpes = pd.to_numeric(kpi_df.get("Sharpe Ratio"), errors="coerce").dropna()
    rsis = pd.to_numeric(kpi_df.get("RSI"), errors="coerce").dropna()
    macd = pd.to_numeric(kpi_df.get("MACD"), errors="coerce")
    signal = pd.to_numeric(kpi_df.get("Signal"), errors="coerce")
    bullish = int(((macd > signal) & macd.notna() & signal.notna()).sum()) if len(kpi_df) else 0

    vol_txt = (
        f"Average annualized volatility is about {vols.mean():.0f}% across names with data."
        if not vols.empty
        else "Volatility data is limited for several holdings."
    )
    beta_txt = (
        f"Average beta is about {betas.mean():.2f}, suggesting "
        + ("above-market" if betas.mean() > 1.05 else "near-market" if betas.mean() > 0.9 else "below-market")
        + " sensitivity vs. the Yahoo benchmark."
        if not betas.empty
        else "Beta is missing for some listings (common for ETFs/alternatives)."
    )
    sharpe_txt = (
        f"{int((sharpes >= 0).sum())} of {len(sharpes)} names show non-negative Sharpe on this window."
        if not sharpes.empty
        else ""
    )
    rsi_txt = ""
    if not rsis.empty:
        hot = int((rsis >= 70).sum())
        cold = int((rsis <= 30).sum())
        if hot:
            rsi_txt = f" {hot} holding(s) look overbought on RSI."
        elif cold:
            rsi_txt = f" {cold} holding(s) look oversold on RSI."

    action = (
        "Consider trimming the highest-volatility names or adding a lower-beta diversifier if risk feels high."
        if not vols.empty and vols.mean() >= 35
        else "Momentum is mixed; rebalance toward names with stronger risk-adjusted trends and clear MACD support."
    )

    body = (
        f"Across **{n}** holdings, {vol_txt} {beta_txt}"
        + (f" {sharpe_txt}" if sharpe_txt else "")
        + (f" MACD is bullish on **{bullish}** of **{n}** names." if n else "")
        + rsi_txt
        + f" {action}"
    )
    return f"## Overall Portfolio Note\n\n{body.strip()}"


def generate_portfolio_ai_markdown(
    current_portfolio: pd.DataFrame,
    candidate_instruments: pd.DataFrame | None = None,
    *,
    model: str | None = None,
) -> str:
    """Call OpenAI with portfolio KPI tables; response includes ## Overall Portfolio Note."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set. Add it to your .env file.")

    candidates = (
        candidate_instruments
        if candidate_instruments is not None and not candidate_instruments.empty
        else pd.DataFrame()
    )
    human = (
        f"Current portfolio:\n{current_portfolio.to_string(index=False)}\n\n"
        f"Instruments under consideration:\n"
        f"{candidates.to_string(index=False) if not candidates.empty else '(none)'}\n\n"
        "Assess each holding and each candidate. You MUST include the section "
        "## Overall Portfolio Note at the end."
    )
    llm = ChatOpenAI(
        model=model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0,
    )
    response = llm.invoke(
        [("system", PORTFOLIO_AI_SYSTEM_PROMPT), ("human", human)]
    )
    content = (response.content or "").strip()
    if "## Overall Portfolio Note" not in content:
        content = content + "\n\n" + format_overall_portfolio_note_heuristic(current_portfolio)
    return content
