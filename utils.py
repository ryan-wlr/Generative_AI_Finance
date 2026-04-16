
import time
import pandas as pd
import yfinance as yf
import numpy as np
import requests
import matplotlib.pyplot as plt

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
        rate = _last_close(yf.Ticker(pair, session=sess))
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
    sess = session or _yahoo_session()
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
            session=sess,
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
            price_native = _last_close(yf.Ticker(sym, session=sess))
        if pd.isna(price_native) or price_native <= 0:
            return np.nan
        rate = fx_cache.get(row["Currency Yahoo"], np.nan)
        if pd.isna(rate) or rate <= 0:
            return np.nan
        return price_native * rate
    except Exception:
        return np.nan

# Build a function that retrives prices and info 
def get_history(ticker, period = "1y", interval = "1d"):
    """
    Fetch historical data for a ticker
    """
    try:
        price_history = yf.Ticker(ticker).history(period=period, interval=interval)
        info = yf.Ticker(ticker).info
        return price_history, info
    except Exception as e:
        print(f"Error fetching history for {ticker}: {e}")
        return None, None

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