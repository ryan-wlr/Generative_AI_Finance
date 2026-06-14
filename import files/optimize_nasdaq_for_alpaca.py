"""
Optimize TradeSmart parameters on a Nasdaq stock and verify Alpaca tradability.

Example:
    python "import files/optimize_nasdaq_for_alpaca.py" --symbol NVDA --mode paper
"""

from __future__ import annotations

import argparse
import itertools
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from utils import get_alpaca_trading_client, get_history, execute_tradesmart_signal_on_alpaca


ANNUAL_BARS_1H_US = 252 * 6.5


def _compute_supertrend_from_ohlc(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    atr_period: int,
    multiplier: float,
) -> tuple[pd.Series, pd.Series]:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1.0 / atr_period, adjust=False, min_periods=atr_period).mean()

    hl2 = (high + low) / 2.0
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    for i in range(1, len(close)):
        if pd.isna(final_upper.iloc[i - 1]) or pd.isna(final_lower.iloc[i - 1]):
            continue
        if (basic_upper.iloc[i] < final_upper.iloc[i - 1]) or (close.iloc[i - 1] > final_upper.iloc[i - 1]):
            final_upper.iloc[i] = basic_upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]

        if (basic_lower.iloc[i] > final_lower.iloc[i - 1]) or (close.iloc[i - 1] < final_lower.iloc[i - 1]):
            final_lower.iloc[i] = basic_lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]

    st_line = pd.Series(index=close.index, dtype=float)
    st_bull = pd.Series(index=close.index, dtype=bool)
    for i in range(len(close)):
        if i == 0:
            st_bull.iloc[i] = True
            st_line.iloc[i] = final_lower.iloc[i]
            continue
        prev_bull = bool(st_bull.iloc[i - 1]) if pd.notna(st_bull.iloc[i - 1]) else True
        if prev_bull:
            st_bull.iloc[i] = close.iloc[i] >= final_lower.iloc[i]
        else:
            st_bull.iloc[i] = close.iloc[i] > final_upper.iloc[i]
        st_line.iloc[i] = final_lower.iloc[i] if st_bull.iloc[i] else final_upper.iloc[i]
    return st_line, st_bull


def _tradesmart_macd_double_cross_events(
    macd: pd.Series,
    signal: pd.Series,
    *,
    zero_touch_eps: float = 1e-10,
) -> tuple[pd.Series, pd.Series]:
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

        if (mv < 0) or (sv < 0):
            long_armed = True
            long_stage = 0
            long_invalid = False
        if (mv > 0) or (sv > 0):
            short_armed = True
            short_stage = 0
            short_invalid = False

        if touch_zero.iloc[i]:
            if long_stage == 1:
                long_invalid = True
            if short_stage == 1:
                short_invalid = True

        if long_armed:
            if (long_stage == 0) and cross_down.iloc[i] and (mv > 0) and (sv > 0):
                long_stage = 1
            elif (long_stage == 1) and cross_up.iloc[i] and (mv > 0) and (sv > 0):
                if not long_invalid:
                    long_evt.iloc[i] = True
                    long_armed = False
                long_stage = 0
                long_invalid = False

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


def _build_signals(price_df: pd.DataFrame, params: dict) -> pd.DataFrame:
    out = price_df[["Open", "High", "Low", "Close", "Volume"]].copy()
    close = out["Close"].astype(float)
    high = out["High"].astype(float)
    low = out["Low"].astype(float)
    vol = pd.to_numeric(out["Volume"], errors="coerce").fillna(0.0)

    out["EMA"] = close.ewm(span=int(params["ema_period"]), adjust=False).mean()

    mfm_den = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / mfm_den
    mfv = mfm.fillna(0.0) * vol
    cmf_period = int(params["cmf_period"])
    out["CMF"] = (mfv.rolling(cmf_period).sum() / vol.rolling(cmf_period).sum().replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan
    )

    ema_fast = close.ewm(span=int(params["macd_fast"]), adjust=False).mean()
    ema_slow = close.ewm(span=int(params["macd_slow"]), adjust=False).mean()
    out["MACD"] = ema_fast - ema_slow
    out["Signal"] = out["MACD"].ewm(span=int(params["macd_signal"]), adjust=False).mean()

    long_evt, short_evt = _tradesmart_macd_double_cross_events(out["MACD"], out["Signal"])
    st_line, st_bull = _compute_supertrend_from_ohlc(
        high,
        low,
        close,
        atr_period=int(params["st_atr_period"]),
        multiplier=float(params["st_multiplier"]),
    )
    out["Supertrend"] = st_line
    out["ST_Bull"] = st_bull

    out["Long_Entry"] = long_evt & (out["CMF"] > 0) & (out["Close"] > out["EMA"]) & out["ST_Bull"]
    out["Short_Entry"] = short_evt & (out["CMF"] < 0) & (out["Close"] < out["EMA"]) & (~out["ST_Bull"])

    return out.dropna(subset=["EMA", "CMF", "MACD", "Signal", "Supertrend"]).copy()


def _backtest_long_only(ind_df: pd.DataFrame, *, cost_bps: float = 2.0) -> dict:
    if ind_df is None or ind_df.empty:
        return {"return": np.nan, "sharpe": np.nan, "max_drawdown": np.nan, "trades": 0}

    pos = pd.Series(0, index=ind_df.index, dtype=float)
    in_pos = 0
    trades = 0
    for i, (_, row) in enumerate(ind_df.iterrows()):
        if i == 0:
            pos.iloc[i] = 0
            continue
        if bool(row["Long_Entry"]) and in_pos == 0:
            in_pos = 1
            trades += 1
        elif bool(row["Short_Entry"]) and in_pos == 1:
            in_pos = 0
        pos.iloc[i] = in_pos

    close = ind_df["Close"].astype(float)
    ret = close.pct_change().fillna(0.0)
    prev_pos = pos.shift(1).fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    costs = turnover * (cost_bps / 10000.0)
    strat_ret = prev_pos * ret - costs

    equity = (1.0 + strat_ret).cumprod()
    if equity.empty:
        return {"return": np.nan, "sharpe": np.nan, "max_drawdown": np.nan, "trades": trades}

    total_return = float(equity.iloc[-1] - 1.0)
    vol = float(strat_ret.std())
    sharpe = float((strat_ret.mean() / vol) * math.sqrt(ANNUAL_BARS_1H_US)) if vol > 0 else np.nan
    drawdown = equity / equity.cummax() - 1.0
    max_dd = float(drawdown.min()) if not drawdown.empty else np.nan
    return {
        "return": total_return,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "trades": int(trades),
    }


def _param_grid() -> list[dict]:
    grid = {
        "ema_period": [100, 150, 200],
        "cmf_period": [10, 20, 30],
        "macd_fast": [8, 12],
        "macd_slow": [21, 26, 34],
        "macd_signal": [7, 9],
        "st_atr_period": [7, 10, 14],
        "st_multiplier": [2.0, 2.5, 3.0],
    }
    keys = list(grid.keys())
    combos = []
    for vals in itertools.product(*(grid[k] for k in keys)):
        p = dict(zip(keys, vals))
        if int(p["macd_fast"]) >= int(p["macd_slow"]):
            continue
        combos.append(p)
    return combos


def _latest_strategy_signal(ind_df: pd.DataFrame) -> str:
    if ind_df is None or ind_df.empty:
        return "Neutral"
    last = ind_df.iloc[-1]
    if bool(last.get("Long_Entry", False)):
        return "Bullish"
    if bool(last.get("Short_Entry", False)):
        return "Bearish"
    return "Neutral"


def _companion_strategy_signals(price_df: pd.DataFrame) -> dict:
    """Compute lightweight companion strategy signals from the same price data."""
    close = price_df["Close"].astype(float)

    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    last_close = float(close.iloc[-1])
    last_ema50 = float(ema50.iloc[-1])
    last_ema200 = float(ema200.iloc[-1])
    if last_close > last_ema50 > last_ema200:
        ma_signal = "Bullish"
    elif last_close < last_ema50 < last_ema200:
        ma_signal = "Bearish"
    else:
        ma_signal = "Neutral"

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = (100 - (100 / (1 + rs))).replace([np.inf, -np.inf], np.nan).dropna()
    rsi_last = float(rsi.iloc[-1]) if not rsi.empty else np.nan
    if np.isfinite(rsi_last) and rsi_last >= 55:
        rsi_signal = "Bullish"
    elif np.isfinite(rsi_last) and rsi_last <= 45:
        rsi_signal = "Bearish"
    else:
        rsi_signal = "Neutral"

    macd_fast = close.ewm(span=12, adjust=False).mean()
    macd_slow = close.ewm(span=26, adjust=False).mean()
    macd = macd_fast - macd_slow
    macd_signal_line = macd.ewm(span=9, adjust=False).mean()
    mv = float(macd.iloc[-1])
    sv = float(macd_signal_line.iloc[-1])
    if mv > sv:
        macd_signal = "Bullish"
    elif mv < sv:
        macd_signal = "Bearish"
    else:
        macd_signal = "Neutral"

    return {
        "MA": ma_signal,
        "RSI": rsi_signal,
        "MACD": macd_signal,
        "RSI_VALUE": rsi_last,
    }


def _aggregate_signal(base_signal: str, companion: dict, min_aligned_signals: int) -> tuple[str, dict]:
    votes = [base_signal, companion.get("MA", "Neutral"), companion.get("RSI", "Neutral"), companion.get("MACD", "Neutral")]
    bulls = sum(1 for v in votes if v == "Bullish")
    bears = sum(1 for v in votes if v == "Bearish")
    threshold = max(1, int(min_aligned_signals))

    if bulls >= threshold and bulls > bears:
        final_signal = "Bullish"
    elif bears >= threshold and bears > bulls:
        final_signal = "Bearish"
    else:
        final_signal = "Neutral"

    details = {
        "optimizer": base_signal,
        "ma": companion.get("MA", "Neutral"),
        "rsi": companion.get("RSI", "Neutral"),
        "macd": companion.get("MACD", "Neutral"),
        "bull_votes": bulls,
        "bear_votes": bears,
        "threshold": threshold,
    }
    return final_signal, details


def _verify_alpaca_symbol(symbol: str, mode: str):
    try:
        client = get_alpaca_trading_client(mode)
        asset = client.get_asset(symbol)
        tradable = bool(getattr(asset, "tradable", False))
        exchange = str(getattr(asset, "exchange", ""))
        status = str(getattr(asset, "status", ""))
        print(f"Alpaca asset check: tradable={tradable} exchange={exchange or 'n/a'} status={status or 'n/a'}")
        if not tradable:
            raise RuntimeError(f"{symbol} is not tradable in this Alpaca account.")
        if "NASDAQ" not in exchange.upper():
            print(f"Warning: {symbol} is tradable, but exchange is {exchange} (not NASDAQ).")
        return client
    except Exception as exc:
        raise RuntimeError(f"Alpaca check failed for {symbol}: {exc}") from exc


def _market_is_open(client) -> bool:
    try:
        clock = client.get_clock()
        is_open = bool(getattr(clock, "is_open", False))
        if is_open:
            print("Market status: OPEN")
        else:
            next_open = getattr(clock, "next_open", None)
            if next_open is not None:
                print(f"Market status: CLOSED (next open: {next_open})")
            else:
                print("Market status: CLOSED")
        return is_open
    except Exception as exc:
        raise RuntimeError(f"Could not read Alpaca market clock: {exc}") from exc


def _wait_until_market_open(client) -> None:
    """Block until Alpaca market clock reports open."""
    while True:
        clock = client.get_clock()
        if bool(getattr(clock, "is_open", False)):
            print("Market status: OPEN")
            return

        next_open = getattr(clock, "next_open", None)
        if next_open is not None:
            now = getattr(clock, "timestamp", None)
            if now is None:
                now = datetime.now(timezone.utc)
            wait_seconds = max(1.0, (next_open - now).total_seconds()) if now is not None else 60.0
            print(f"Market status: CLOSED (next open: {next_open})")
            print(f"Waiting until market open (~{wait_seconds / 60.0:.1f} minutes)...")
            time.sleep(wait_seconds)
        else:
            print("Market status: CLOSED (next open unavailable). Retrying in 60 seconds...")
            time.sleep(60)


def run_optimization(
    symbol: str,
    interval: str,
    period: str,
    mode: str,
    min_trades: int,
    cost_bps: float,
    *,
    require_market_open: bool,
    wait_for_open: bool,
) -> dict | None:
    symbol = symbol.strip().upper()
    client = _verify_alpaca_symbol(symbol, mode)

    if require_market_open and not _market_is_open(client):
        if wait_for_open:
            _wait_until_market_open(client)
        else:
            print("Skipping optimization because market is closed.")
            return None

    history, _ = get_history(symbol, period=period, interval=interval)
    if history is None or history.empty:
        raise RuntimeError(f"No price history available for {symbol} at interval={interval}, period={period}.")
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(history.columns)):
        raise RuntimeError(f"History for {symbol} is missing required columns: {sorted(required)}")

    data = history.sort_index().copy()
    if len(data) < 400:
        raise RuntimeError(f"Not enough bars for optimization ({len(data)} bars). Increase period.")

    split_i = int(len(data) * 0.7)
    train = data.iloc[:split_i].copy()
    test = data.iloc[split_i:].copy()

    rows = []
    for p in _param_grid():
        train_ind = _build_signals(train, p)
        m_train = _backtest_long_only(train_ind, cost_bps=cost_bps)
        if m_train["trades"] < min_trades or not np.isfinite(m_train["sharpe"]):
            continue
        score = float(m_train["sharpe"]) + 0.25 * float(m_train["return"]) + 0.5 * float(m_train["max_drawdown"])

        test_ind = _build_signals(test, p)
        m_test = _backtest_long_only(test_ind, cost_bps=cost_bps)

        rows.append(
            {
                **p,
                "train_return": m_train["return"],
                "train_sharpe": m_train["sharpe"],
                "train_max_dd": m_train["max_drawdown"],
                "train_trades": m_train["trades"],
                "test_return": m_test["return"],
                "test_sharpe": m_test["sharpe"],
                "test_max_dd": m_test["max_drawdown"],
                "test_trades": m_test["trades"],
                "score": score,
            }
        )

    if not rows:
        raise RuntimeError("No parameter sets passed constraints. Lower min-trades or increase period.")

    res = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    best = res.iloc[0]

    print(f"\nOptimized symbol: {symbol}")
    print(f"Bars: {len(data)} | Train: {len(train)} | Test: {len(test)} | Interval: {interval} | Period: {period}")
    print(f"Search candidates kept: {len(res)}")

    print("\nBest parameters:")
    for k in ["ema_period", "cmf_period", "macd_fast", "macd_slow", "macd_signal", "st_atr_period", "st_multiplier"]:
        print(f"  {k}: {best[k]}")

    print("\nBest performance:")
    print(f"  Train return: {best['train_return'] * 100:.2f}%")
    print(f"  Train Sharpe: {best['train_sharpe']:.2f}")
    print(f"  Train max drawdown: {best['train_max_dd'] * 100:.2f}%")
    print(f"  Train trades: {int(best['train_trades'])}")
    print(f"  Test return: {best['test_return'] * 100:.2f}%")
    print(f"  Test Sharpe: {best['test_sharpe']:.2f}")
    print(f"  Test max drawdown: {best['test_max_dd'] * 100:.2f}%")
    print(f"  Test trades: {int(best['test_trades'])}")

    print("\nTop 5 candidates by score:")
    cols = [
        "ema_period",
        "cmf_period",
        "macd_fast",
        "macd_slow",
        "macd_signal",
        "st_atr_period",
        "st_multiplier",
        "train_return",
        "train_sharpe",
        "test_return",
        "test_sharpe",
        "score",
    ]
    top = res[cols].head(5).copy()
    pd.options.display.float_format = lambda x: f"{x:,.4f}"
    print(top.to_string(index=False))

    best_params = {
        "ema_period": int(best["ema_period"]),
        "cmf_period": int(best["cmf_period"]),
        "macd_fast": int(best["macd_fast"]),
        "macd_slow": int(best["macd_slow"]),
        "macd_signal": int(best["macd_signal"]),
        "st_atr_period": int(best["st_atr_period"]),
        "st_multiplier": float(best["st_multiplier"]),
    }
    all_ind = _build_signals(data, best_params)
    latest_signal = _latest_strategy_signal(all_ind)
    companion = _companion_strategy_signals(data)
    rsi_txt = f"{companion['RSI_VALUE']:.1f}" if np.isfinite(companion["RSI_VALUE"]) else "n/a"
    print(f"\nLatest optimized strategy signal: {latest_signal}")
    print(
        "Companion signals: "
        f"MA={companion['MA']} | RSI={companion['RSI']} (value={rsi_txt}) | "
        f"MACD={companion['MACD']}"
    )

    return {
        "symbol": symbol,
        "mode": mode,
        "client": client,
        "best_params": best_params,
        "latest_signal": latest_signal,
        "companion": companion,
    }


def execute_optimized_signal(
    *,
    symbol: str,
    mode: str,
    signal: str,
    companion: dict,
    min_aligned_signals: int,
    order_qty: int,
    allow_short_entries: bool,
    client=None,
) -> None:
    final_signal, agg = _aggregate_signal(signal, companion, min_aligned_signals)
    print("\nSignal aggregation:")
    print(
        f"  Optimizer={agg['optimizer']} | MA={agg['ma']} | RSI={agg['rsi']} | MACD={agg['macd']} | "
        f"Bull votes={agg['bull_votes']} | Bear votes={agg['bear_votes']} | Threshold={agg['threshold']}"
    )
    print(f"  Final execution signal: {final_signal}")

    if client is None:
        client = get_alpaca_trading_client(mode)
    res = execute_tradesmart_signal_on_alpaca(
        client,
        symbol,
        final_signal,
        order_qty=max(1, int(order_qty)),
        allow_short_entries=bool(allow_short_entries),
    )
    print("\nAlpaca execution result:")
    for k in ["Ticker", "Signal", "Action", "Orders", "Status", "Note"]:
        print(f"  {k}: {res.get(k)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize a TradeSmart-like strategy for an Alpaca-tradable Nasdaq stock.")
    parser.add_argument("--symbol", default="NVDA", help="Ticker symbol (default: NVDA)")
    parser.add_argument("--interval", default="1h", help="Yahoo interval (default: 1h)")
    parser.add_argument("--period", default="730d", help="Yahoo period (default: 730d)")
    parser.add_argument("--mode", default="paper", choices=["paper", "live"], help="Alpaca mode for tradability check")
    parser.add_argument("--min-trades", type=int, default=6, help="Minimum train trades required (default: 6)")
    parser.add_argument("--cost-bps", type=float, default=2.0, help="Round-turn trading cost per position change in bps")
    parser.add_argument("--execute-trade", action="store_true", help="Execute latest optimized signal on Alpaca")
    parser.add_argument("--order-qty", type=int, default=1, help="Order quantity when --execute-trade is used")
    parser.add_argument(
        "--min-aligned-signals",
        type=int,
        default=2,
        help="Minimum bullish/bearish votes across optimizer+companion signals before trading (default: 2)",
    )
    parser.add_argument(
        "--allow-short-entries",
        action="store_true",
        help="Allow opening short positions on bearish signals when executing trades",
    )
    parser.add_argument(
        "--allow-when-closed",
        action="store_true",
        help="Allow optimization even if market is closed (default is to skip when closed)",
    )
    parser.add_argument(
        "--wait-for-open",
        action="store_true",
        help="If market is closed, wait until it opens, then run optimization",
    )
    return parser.parse_args()


def main() -> None:
    here = Path(__file__).resolve().parent
    load_dotenv(here / ".env")
    load_dotenv(here.parent / ".env", override=False)

    args = parse_args()
    result = run_optimization(
        symbol=args.symbol,
        interval=args.interval,
        period=args.period,
        mode=args.mode,
        min_trades=max(0, int(args.min_trades)),
        cost_bps=max(0.0, float(args.cost_bps)),
        require_market_open=not bool(args.allow_when_closed),
        wait_for_open=bool(args.wait_for_open),
    )

    if result is None:
        return

    if args.execute_trade:
        execute_optimized_signal(
            symbol=result["symbol"],
            mode=result["mode"],
            signal=result["latest_signal"],
            companion=result.get("companion", {}),
            min_aligned_signals=max(1, int(args.min_aligned_signals)),
            order_qty=max(1, int(args.order_qty)),
            allow_short_entries=bool(args.allow_short_entries),
            client=result.get("client"),
        )


if __name__ == "__main__":
    main()
