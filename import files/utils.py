
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
    Build a price DataFrame (DatetimeIndex, OHLCV) from Yahoo's chart endpoint.
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
        opens = q0.get("open") or []
        highs = q0.get("high") or []
        lows = q0.get("low") or []
        closes = q0.get("close") or []
        vols = q0.get("volume") or []
        if not ts or not closes:
            return None
        n = min(len(ts), len(opens), len(highs), len(lows), len(closes), len(vols))
        if n < 1:
            return None
        ts = ts[:n]
        opens = opens[:n]
        highs = highs[:n]
        lows = lows[:n]
        closes = closes[:n]
        vols = vols[:n]
        idx = pd.to_datetime(ts, unit="s")
        df = pd.DataFrame(
            {
                "Open": opens,
                "High": highs,
                "Low": lows,
                "Close": closes,
                "Volume": vols,
            },
            index=idx,
        )
        df = df.loc[pd.notna(df["Close"]) & (df["Close"] > 0)]
        for col in ("Open", "High", "Low"):
            if col in df.columns:
                df[col] = df[col].where(pd.notna(df[col]), df["Close"])
        if "Volume" in df.columns:
            df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0.0)
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


def _compute_supertrend_from_ohlc(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    atr_period: int = 10,
    multiplier: float = 3.0,
) -> tuple[pd.Series, pd.Series]:
    """
    Supertrend line + trend direction from OHLC.
    Returns (supertrend_line, is_bullish).
    """
    h = high.astype(float)
    l = low.astype(float)
    c = close.astype(float)

    prev_close = c.shift(1)
    tr = pd.concat(
        [
            (h - l),
            (h - prev_close).abs(),
            (l - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / atr_period, adjust=False, min_periods=atr_period).mean()

    hl2 = (h + l) / 2.0
    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()

    for i in range(1, len(c)):
        if pd.isna(final_upper.iloc[i - 1]):
            continue
        if (basic_upper.iloc[i] < final_upper.iloc[i - 1]) or (c.iloc[i - 1] > final_upper.iloc[i - 1]):
            final_upper.iloc[i] = basic_upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]

        if (basic_lower.iloc[i] > final_lower.iloc[i - 1]) or (c.iloc[i - 1] < final_lower.iloc[i - 1]):
            final_lower.iloc[i] = basic_lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]

    st_line = pd.Series(index=c.index, dtype=float)
    bullish = pd.Series(index=c.index, dtype=bool)

    for i in range(len(c)):
        if i == 0:
            bullish.iloc[i] = True
            st_line.iloc[i] = final_lower.iloc[i]
            continue

        prev_bull = bool(bullish.iloc[i - 1]) if pd.notna(bullish.iloc[i - 1]) else True
        if prev_bull:
            bullish.iloc[i] = c.iloc[i] >= final_lower.iloc[i]
        else:
            bullish.iloc[i] = c.iloc[i] > final_upper.iloc[i]
        st_line.iloc[i] = final_lower.iloc[i] if bullish.iloc[i] else final_upper.iloc[i]

    return st_line, bullish


def _tradesmart_macd_double_cross_events(
    macd: pd.Series,
    signal: pd.Series,
    *,
    zero_touch_eps: float = 1e-10,
) -> tuple[pd.Series, pd.Series]:
    """
    TradeSmart-like MACD event sequencing.

    Long event:
    - MACD/Signal must first re-arm by going below zero,
    - then a cross-down and cross-up sequence above zero,
    - and no zero-line touch between those two crosses.

    Short event:
    - MACD/Signal must first re-arm by going above zero,
    - then a cross-up and cross-down sequence below zero,
    - and no zero-line touch between those two crosses.
    """
    m = macd.astype(float)
    s = signal.astype(float)

    cross_up = (m > s) & (m.shift(1) <= s.shift(1))
    cross_down = (m < s) & (m.shift(1) >= s.shift(1))
    touch_zero = (m.abs() <= zero_touch_eps) | (s.abs() <= zero_touch_eps)

    long_evt = pd.Series(False, index=m.index, dtype=bool)
    short_evt = pd.Series(False, index=m.index, dtype=bool)

    long_armed = False
    short_armed = False
    long_stage = 0
    short_stage = 0
    long_invalid = False
    short_invalid = False

    for i in range(len(m)):
        mv = m.iloc[i]
        sv = s.iloc[i]
        if pd.isna(mv) or pd.isna(sv):
            continue

        # Re-arm conditions for the next valid sequence.
        if (mv < 0) or (sv < 0):
            long_armed = True
            long_stage = 0
            long_invalid = False
        if (mv > 0) or (sv > 0):
            short_armed = True
            short_stage = 0
            short_invalid = False

        # Zero-line touch after first stage invalidates the pending setup.
        if touch_zero.iloc[i]:
            if long_stage == 1:
                long_invalid = True
            if short_stage == 1:
                short_invalid = True

        # Long: down-cross then up-cross above zero.
        if long_armed:
            if (long_stage == 0) and cross_down.iloc[i] and (mv > 0) and (sv > 0):
                long_stage = 1
            elif (long_stage == 1) and cross_up.iloc[i] and (mv > 0) and (sv > 0):
                if not long_invalid:
                    long_evt.iloc[i] = True
                    long_armed = False
                long_stage = 0
                long_invalid = False

        # Short: up-cross then down-cross below zero.
        if short_armed:
            if (short_stage == 0) and cross_up.iloc[i] and (mv < 0) and (sv < 0):
                short_stage = 1
            elif (short_stage == 1) and cross_down.iloc[i] and (mv < 0) and (sv < 0):
                if not short_invalid:
                    short_evt.iloc[i] = True
                    short_armed = False
                short_stage = 0
                short_invalid = False

    return long_evt, short_evt


def compute_macd_cmf_ema_supertrend(
    ticker,
    *,
    ema_period: int = 200,
    cmf_period: int = 20,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    st_atr_period: int = 10,
    st_multiplier: float = 3.0,
):
    """TradeSmart-style strategy components from price history.

    Uses MACD double-cross sequencing with zero-line re-arm/touch constraints,
    then applies CMF, EMA, and Supertrend filters for final long/short events.
    Returns DataFrame with indicators and latest summary dict.
    """
    price_history, _ = get_history(ticker)
    if price_history is None or price_history.empty:
        return None, None
    required = {"Close", "High", "Low", "Volume"}
    if not required.issubset(set(price_history.columns)):
        return None, None

    df = price_history[["Close", "High", "Low", "Volume"]].copy()
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = pd.to_numeric(df["Volume"], errors="coerce").fillna(0.0)

    df["EMA"] = close.ewm(span=ema_period, adjust=False).mean()

    mfm_den = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / mfm_den
    mfv = mfm.fillna(0.0) * volume
    vol_sum = volume.rolling(cmf_period).sum()
    df["CMF"] = (mfv.rolling(cmf_period).sum() / vol_sum.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    ema_fast = close.ewm(span=macd_fast, adjust=False).mean()
    ema_slow = close.ewm(span=macd_slow, adjust=False).mean()
    df["MACD"] = ema_fast - ema_slow
    df["Signal"] = df["MACD"].ewm(span=macd_signal, adjust=False).mean()
    df["Histogram"] = df["MACD"] - df["Signal"]

    long_evt, short_evt = _tradesmart_macd_double_cross_events(df["MACD"], df["Signal"])
    df["MACD_Long_Event"] = long_evt
    df["MACD_Short_Event"] = short_evt

    st_line, st_bull = _compute_supertrend_from_ohlc(
        high,
        low,
        close,
        atr_period=st_atr_period,
        multiplier=st_multiplier,
    )
    df["Supertrend"] = st_line
    df["ST_Bull"] = st_bull

    df["Long_Entry"] = (
        df["MACD_Long_Event"]
        & (df["CMF"] > 0)
        & (df["Close"] > df["EMA"])
        & df["ST_Bull"]
    )
    df["Short_Entry"] = (
        df["MACD_Short_Event"]
        & (df["CMF"] < 0)
        & (df["Close"] < df["EMA"])
        & (~df["ST_Bull"])
    )

    out = df.dropna(subset=["EMA", "CMF", "MACD", "Signal", "Supertrend"]).copy()
    if out.empty:
        return None, None

    last = out.iloc[-1]
    if bool(last["Long_Entry"]):
        strategy_signal = "Bullish"
    elif bool(last["Short_Entry"]):
        strategy_signal = "Bearish"
    else:
        strategy_signal = "Neutral"

    recent = out.tail(200)
    recent_long_idx = recent.index[recent["Long_Entry"]]
    recent_short_idx = recent.index[recent["Short_Entry"]]
    if len(recent_long_idx) and len(recent_short_idx):
        latest_idx = max(recent_long_idx[-1], recent_short_idx[-1])
        last_signal = "Bullish" if latest_idx == recent_long_idx[-1] else "Bearish"
    elif len(recent_long_idx):
        latest_idx = recent_long_idx[-1]
        last_signal = "Bullish"
    elif len(recent_short_idx):
        latest_idx = recent_short_idx[-1]
        last_signal = "Bearish"
    else:
        latest_idx = None
        last_signal = "Neutral"

    summary = {
        "close": float(last["Close"]),
        "ema": float(last["EMA"]),
        "cmf": float(last["CMF"]),
        "macd": float(last["MACD"]),
        "signal": float(last["Signal"]),
        "st_bull": bool(last["ST_Bull"]),
        "strategy_signal": strategy_signal,
        "recent_signal": last_signal,
        "recent_signal_date": latest_idx.strftime("%Y-%m-%d") if latest_idx is not None else None,
    }
    return out, summary


def plot_macd_cmf_ema_supertrend(indicator_df: pd.DataFrame, ticker: str):
    """
    Matplotlib figure for MACD+CMF+EMA+Supertrend strategy diagnostics.
    """
    if indicator_df is None or indicator_df.empty:
        return None

    fig, (ax_p, ax_m, ax_c) = plt.subplots(
        3,
        1,
        figsize=(11, 9),
        sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1.2, 1.0]},
    )

    ax_p.plot(indicator_df.index, indicator_df["Close"], label="Close", color="#2C3E50", linewidth=1.4)
    ax_p.plot(indicator_df.index, indicator_df["EMA"], label="EMA", color="#E67E22", linewidth=1.2)
    ax_p.plot(indicator_df.index, indicator_df["Supertrend"], label="Supertrend", color="#16A085", linewidth=1.2)
    ax_p.set_title(f"{ticker} — MACD + CMF + EMA + Supertrend")
    ax_p.set_ylabel("Price")
    ax_p.grid(True, alpha=0.25)
    ax_p.legend(loc="upper left")

    ax_m.plot(indicator_df.index, indicator_df["MACD"], label="MACD", color="#1F77B4")
    ax_m.plot(indicator_df.index, indicator_df["Signal"], label="Signal", color="#FF7F0E")
    ax_m.bar(indicator_df.index, indicator_df["Histogram"], label="Histogram", color="#95A5A6", alpha=0.4)
    ax_m.axhline(0, color="#666666", linewidth=1)
    ax_m.set_ylabel("MACD")
    ax_m.grid(True, alpha=0.25)
    ax_m.legend(loc="upper left")

    ax_c.plot(indicator_df.index, indicator_df["CMF"], label="CMF", color="#8E44AD")
    ax_c.axhline(0, color="#666666", linewidth=1)
    ax_c.set_ylabel("CMF")
    ax_c.set_xlabel("Date")
    ax_c.grid(True, alpha=0.25)
    ax_c.legend(loc="upper left")

    fig.tight_layout()
    return fig


def build_tradesmart_paper_trades(
    ticker: str,
    indicator_df: pd.DataFrame,
    *,
    lookback_bars: int = 200,
) -> tuple[pd.DataFrame, dict]:
    """
    Build a paper-trade log from TradeSmart long/short entry events.

    Rules:
    - Long_Entry opens long (and closes short if one is open).
    - Short_Entry opens short (and closes long if one is open).
    - No position sizing or fees; this is signal-driven educational tracking.
    """
    if indicator_df is None or indicator_df.empty:
        return pd.DataFrame(), {"position": "Flat", "last_action": "None"}

    df = indicator_df.tail(max(20, int(lookback_bars))).copy()
    needed = {"Close", "Long_Entry", "Short_Entry"}
    if not needed.issubset(set(df.columns)):
        return pd.DataFrame(), {"position": "Flat", "last_action": "None"}

    trades = []
    position = 0  # 1 long, -1 short, 0 flat
    last_action = "None"

    for idx, row in df.iterrows():
        price = float(row["Close"])
        is_long = bool(row["Long_Entry"])
        is_short = bool(row["Short_Entry"])
        dt = idx.strftime("%Y-%m-%d")

        if is_long:
            if position == -1:
                trades.append(
                    {
                        "Date": dt,
                        "Ticker": ticker,
                        "Action": "BUY_TO_CLOSE",
                        "Price": price,
                        "Reason": "Opposite TradeSmart long signal",
                    }
                )
            if position <= 0:
                trades.append(
                    {
                        "Date": dt,
                        "Ticker": ticker,
                        "Action": "BUY",
                        "Price": price,
                        "Reason": "TradeSmart long entry",
                    }
                )
                position = 1
                last_action = "BUY"

        if is_short:
            if position == 1:
                trades.append(
                    {
                        "Date": dt,
                        "Ticker": ticker,
                        "Action": "SELL_TO_CLOSE",
                        "Price": price,
                        "Reason": "Opposite TradeSmart short signal",
                    }
                )
            if position >= 0:
                trades.append(
                    {
                        "Date": dt,
                        "Ticker": ticker,
                        "Action": "SELL",
                        "Price": price,
                        "Reason": "TradeSmart short entry",
                    }
                )
                position = -1
                last_action = "SELL"

    position_text = "Long" if position == 1 else "Short" if position == -1 else "Flat"
    state = {
        "position": position_text,
        "last_action": last_action,
        "bars_scanned": int(len(df)),
    }
    if not trades:
        return pd.DataFrame(), state

    out = pd.DataFrame(trades)
    out["Price"] = pd.to_numeric(out["Price"], errors="coerce")
    return out, state


def _alpaca_credentials_from_env(mode: str = "paper") -> tuple[str, str, str]:
    """Load Alpaca credentials for paper/live mode from environment variables."""
    m = (mode or "paper").strip().lower()
    prefix = "ALPACA_PAPER" if m == "paper" else "ALPACA_LIVE"
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    api_secret = os.getenv(f"{prefix}_API_SECRET", "").strip()
    base_url = os.getenv(f"{prefix}_BASE_URL", "").strip()
    if not api_key or not api_secret or not base_url:
        raise ValueError(
            f"Missing {m} credentials. Set {prefix}_API_KEY, {prefix}_API_SECRET, and {prefix}_BASE_URL."
        )
    return api_key, api_secret, base_url


def get_alpaca_trading_client(mode: str = "paper"):
    """Create Alpaca TradingClient for paper/live mode using .env credentials."""
    from alpaca.trading.client import TradingClient

    m = (mode or "paper").strip().lower()
    api_key, api_secret, base_url = _alpaca_credentials_from_env(m)
    return TradingClient(
        api_key=api_key,
        secret_key=api_secret,
        paper=(m == "paper"),
        url_override=base_url,
    )


def _alpaca_position_qty(client, symbol: str) -> int:
    try:
        pos = client.get_open_position(symbol)
    except Exception:
        return 0
    try:
        return int(float(pos.qty))
    except Exception:
        return 0


def _alpaca_is_tradable(client, symbol: str) -> bool:
    try:
        asset = client.get_asset(symbol)
        return bool(getattr(asset, "tradable", False))
    except Exception:
        return False


def _alpaca_market_is_open(client) -> bool:
    try:
        return bool(client.get_clock().is_open)
    except Exception:
        return False


def execute_tradesmart_signal_on_alpaca(
    client,
    symbol: str,
    signal: str,
    *,
    order_qty: int = 1,
    allow_short_entries: bool = False,
) -> dict:
    """
    Execute TradeSmart signal on Alpaca.

    Long-only default behavior:
    - Bullish: open long if flat.
    - Bearish: close long if open.

    If allow_short_entries=True:
    - Bearish can also open a short after closing long.
    """
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    sym = str(symbol).strip().upper()
    sig = str(signal or "Neutral").strip().title()
    qty = max(1, int(order_qty))

    result = {
        "Ticker": sym,
        "Signal": sig,
        "Action": "NO_ACTION",
        "Orders": 0,
        "Status": "ok",
        "Note": "",
    }

    if not _alpaca_is_tradable(client, sym):
        result["Status"] = "skipped"
        result["Note"] = "Symbol not tradable in this Alpaca account"
        return result

    pos_qty = _alpaca_position_qty(client, sym)

    def _submit(side, q):
        req = MarketOrderRequest(symbol=sym, qty=int(q), side=side, time_in_force=TimeInForce.DAY)
        client.submit_order(order_data=req)
        result["Orders"] += 1

    try:
        if sig == "Bullish":
            if pos_qty < 0:
                _submit(OrderSide.BUY, abs(pos_qty))
                pos_qty = 0
            if pos_qty == 0:
                _submit(OrderSide.BUY, qty)
                result["Action"] = "BUY"
                result["Note"] = "Opened long from bullish signal"
            else:
                result["Action"] = "HOLD_LONG"
                result["Note"] = "Already long"

        elif sig == "Bearish":
            if pos_qty > 0:
                _submit(OrderSide.SELL, pos_qty)
                pos_qty = 0
                result["Action"] = "CLOSE_LONG"
                result["Note"] = "Closed long from bearish signal"
            if allow_short_entries and pos_qty == 0:
                _submit(OrderSide.SELL, qty)
                result["Action"] = "OPEN_SHORT"
                result["Note"] = "Opened short from bearish signal"
            elif result["Action"] == "NO_ACTION":
                result["Action"] = "HOLD_FLAT"
                result["Note"] = "No long position to close"

        else:
            result["Action"] = "HOLD"
            result["Note"] = "Neutral signal"

        if not _alpaca_market_is_open(client):
            result["Note"] = (result["Note"] + " | Market closed: DAY order may queue").strip()

        return result
    except Exception as exc:
        result["Status"] = "error"
        result["Note"] = str(exc)
        return result


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
