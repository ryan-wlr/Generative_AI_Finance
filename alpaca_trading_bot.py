"""
Simple Alpaca trading bot runner.

Features:
- Prompts for paper or live trading mode at startup.
- Trades only during market hours.
- Sleeps while market is closed and resumes when open.

Environment variables expected (see import files/.env):
- ALPACA_PAPER_API_KEY
- ALPACA_PAPER_API_SECRET
- ALPACA_PAPER_BASE_URL
- ALPACA_LIVE_API_KEY
- ALPACA_LIVE_API_SECRET
- ALPACA_LIVE_BASE_URL
"""

from __future__ import annotations

import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest
from dotenv import load_dotenv

from utils import _yahoo_session, get_history, format_new_instrument_assessment


def init_log_file(mode: str) -> Path:
    """Create and return a log file path for this bot session."""
    logs_dir = Path(__file__).resolve().parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return logs_dir / f"alpaca_bot_{mode}_{stamp}.log"


def bot_log(message: str, log_file: Path | None = None) -> None:
    """Print to console and append the same message to a log file."""
    print(message)
    if log_file is None:
        return
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(message + "\n")


def load_env_files() -> None:
    """Load .env from project root and fallback folder used in this repo."""
    root_env = Path(__file__).resolve().parent / ".env"
    import_files_env = Path(__file__).resolve().parent / "import files" / ".env"
    if root_env.exists():
        load_dotenv(root_env)
    if import_files_env.exists():
        load_dotenv(import_files_env, override=False)


def ask_mode() -> str:
    while True:
        mode = input("Choose trading mode ([P]aper / [L]ive): ").strip().lower()
        if mode in {"p", "paper"}:
            return "paper"
        if mode in {"l", "live"}:
            confirm = input("LIVE mode selected. Type 'YES' to continue: ").strip()
            if confirm == "YES":
                return "live"
            print("Live mode not confirmed. Please choose again.")
            continue
        print("Invalid choice. Enter P for paper or L for live.")


def get_credentials(mode: str) -> tuple[str, str, str]:
    prefix = "ALPACA_PAPER" if mode == "paper" else "ALPACA_LIVE"
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    api_secret = os.getenv(f"{prefix}_API_SECRET", "").strip()
    base_url = os.getenv(f"{prefix}_BASE_URL", "").strip()

    if not api_key or not api_secret or not base_url:
        raise RuntimeError(
            f"Missing credentials for {mode} mode. "
            f"Please set {prefix}_API_KEY, {prefix}_API_SECRET, and {prefix}_BASE_URL in .env."
        )

    return api_key, api_secret, base_url


def ask_bot_settings() -> tuple[int, int, int, float]:
    qty_text = input("Order quantity (default 1): ").strip() or "1"
    qty = int(qty_text)
    if qty <= 0:
        raise ValueError("Quantity must be a positive integer.")

    interval_text = input("Check interval in seconds while market is open (default 60): ").strip() or "60"
    interval_seconds = int(interval_text)
    if interval_seconds < 5:
        interval_seconds = 5

    eod_text = input("Force-close positions this many minutes before market close (default 10): ").strip() or "10"
    eod_close_minutes = int(eod_text)
    if eod_close_minutes < 0:
        eod_close_minutes = 0

    loss_text = input(
        "Close open positions when unrealized P/L drops below this amount (default 0 = any loss): "
    ).strip() or "0"
    loss_close_threshold = float(loss_text)

    return qty, interval_seconds, eod_close_minutes, loss_close_threshold


def get_position_qty(client: TradingClient, symbol: str) -> int:
    try:
        pos = client.get_open_position(symbol)
    except Exception:
        return 0

    try:
        return int(float(pos.qty))
    except Exception:
        return 0


def get_unrealized_pl(client: TradingClient, symbol: str) -> float | None:
    """Return unrealized P/L in account currency for an open position, else None."""
    try:
        pos = client.get_open_position(symbol)
    except Exception:
        return None

    raw = getattr(pos, "unrealized_pl", None)
    if raw is None:
        return None

    try:
        return float(raw)
    except Exception:
        return None


def _extract_recommendation(assessment_md: str) -> str:
    marker = "*   **Recommendation:**"
    if marker not in assessment_md:
        return ""
    rec = assessment_md.split(marker, 1)[1].strip().lower()
    return rec


def recommendation_to_action(recommendation: str, position_qty: int) -> str:
    """Map Investment Possibilities recommendation text to bot action."""
    rec = recommendation.lower()
    if rec.startswith("buy"):
        return "BUY"
    if rec.startswith("hold / accumulate"):
        return "BUY" if position_qty <= 0 else "HOLD"
    if rec.startswith("hold"):
        return "HOLD"
    if rec.startswith("caution") or rec.startswith("no action"):
        return "CLOSE" if position_qty > 0 else "HOLD"
    return "HOLD"


def symbol_action_from_investment_possibilities(symbol: str, position_qty: int, session) -> tuple[str, str]:
    ph, info = get_history(symbol, session=session)
    if ph is None or ph.empty or "Close" not in ph.columns:
        return "HOLD", "insufficient-history"

    assessment = format_new_instrument_assessment(symbol, ph, info, item_index=1)
    recommendation = _extract_recommendation(assessment)
    if not recommendation:
        return "HOLD", "no-recommendation"

    action = recommendation_to_action(recommendation, position_qty)
    return action, recommendation


def is_symbol_tradable(client: TradingClient, symbol: str) -> bool:
    """Return True if symbol is tradable in Alpaca account; False otherwise."""
    try:
        asset = client.get_asset(symbol)
        tradable = getattr(asset, "tradable", False)
        return bool(tradable)
    except Exception:
        return False


def place_market_order(
    client: TradingClient,
    symbol: str,
    side: OrderSide,
    qty: int,
    log_file: Path | None = None,
) -> None:
    req = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=side,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(order_data=req)
    bot_log(f"[{datetime.now().isoformat(timespec='seconds')}] Placed {side.value} order: {order.id}", log_file)


def close_position(client: TradingClient, symbol: str, position_qty: int, log_file: Path | None = None) -> None:
    """Close an open long/short position using a market order."""
    if position_qty > 0:
        place_market_order(client, symbol, OrderSide.SELL, position_qty, log_file=log_file)
    elif position_qty < 0:
        place_market_order(client, symbol, OrderSide.BUY, abs(position_qty), log_file=log_file)


def sleep_until_market_open(client: TradingClient, log_file: Path | None = None) -> None:
    while True:
        clock = client.get_clock()
        if clock.is_open:
            bot_log("Market is now open. Waking bot and resuming trading loop.", log_file)
            return

        now_utc = datetime.now(timezone.utc)
        remaining = max(0.0, (clock.next_open - now_utc).total_seconds())

        if remaining <= 0:
            time.sleep(10)
            continue

        total_minutes = math.ceil(remaining / 60.0)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        next_open_et = clock.next_open.astimezone(ZoneInfo("America/New_York"))
        next_open_local = clock.next_open.astimezone()

        bot_log(
            "Market closed. Sleeping until market opens. "
            f"Time until open: {hours}h {minutes}m | "
            f"Next open (ET): {next_open_et.strftime('%Y-%m-%d %I:%M %p %Z')} | "
            f"Local: {next_open_local.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            log_file,
        )

        # Sleep in short chunks so we can keep the user updated.
        time.sleep(min(remaining, 60))


def run_bot(portfolio_tickers: list[str] | None = None) -> None:
    load_env_files()

    mode = ask_mode()
    api_key, api_secret, base_url = get_credentials(mode)
    buy_qty, open_interval_seconds, eod_close_minutes, loss_close_threshold = ask_bot_settings()
    log_file = init_log_file(mode)

    paper_flag = mode == "paper"
    client = TradingClient(api_key=api_key, secret_key=api_secret, paper=paper_flag, url_override=base_url)

    if portfolio_tickers:
        symbols = [str(t).strip().upper() for t in portfolio_tickers if str(t).strip()]
    else:
        default_csv = "assets 2025-07-31.csv"
        csv_path = input(f"Portfolio CSV path [{default_csv}]: ").strip() or default_csv
        if not os.path.exists(csv_path):
            raise RuntimeError(f"Portfolio CSV not found: {csv_path}")
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        if "Ticker" not in df.columns:
            raise RuntimeError("Portfolio CSV missing required column: Ticker")
        symbols = [str(t).strip().upper() for t in df["Ticker"].dropna().tolist() if str(t).strip()]

    # Keep order, remove duplicates.
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        raise RuntimeError("No portfolio symbols available to trade.")

    sess = _yahoo_session()

    account = client.get_account()
    bot_log(
        f"Connected to Alpaca ({mode.upper()}). "
        f"Account status: {account.status}, buying power: {account.buying_power}",
        log_file,
    )
    bot_log(f"Session log file: {log_file}", log_file)
    bot_log("Bot started for portfolio symbols:", log_file)
    bot_log(", ".join(symbols), log_file)
    bot_log("Decisions come from Investment Possibilities recommendations (Buy/Hold/Caution).", log_file)
    bot_log("Actions: BUY, HOLD, CLOSE (close = sell full open position).", log_file)
    bot_log(
        f"Risk controls: EOD close window={eod_close_minutes} minutes, "
        f"loss-close threshold={loss_close_threshold:.2f}",
        log_file,
    )
    bot_log("It will sleep when market is closed and wake when open.", log_file)
    bot_log("Press Ctrl+C only if you want to request bot exit.", log_file)

    while True:
        try:
            clock = client.get_clock()

            if not clock.is_open:
                sleep_until_market_open(client, log_file=log_file)
                continue

            seconds_to_close = max(0.0, (clock.next_close - datetime.now(timezone.utc)).total_seconds())
            minutes_to_close = seconds_to_close / 60.0
            if minutes_to_close <= eod_close_minutes:
                ts = datetime.now().isoformat(timespec="seconds")
                bot_log(
                    f"[{ts}] Market close window reached (<= {eod_close_minutes}m). "
                    "Force-closing all open portfolio positions.",
                    log_file,
                )
                for symbol in symbols:
                    position_qty = get_position_qty(client, symbol)
                    if position_qty != 0:
                        bot_log(f"- {symbol}: end-of-day close for qty {position_qty}", log_file)
                        close_position(client, symbol, position_qty, log_file=log_file)

                sleep_until_market_open(client, log_file=log_file)
                continue

            ts = datetime.now().isoformat(timespec="seconds")
            bot_log(f"[{ts}] Market OPEN | scanning portfolio symbols...", log_file)

            for symbol in symbols:
                if not is_symbol_tradable(client, symbol):
                    bot_log(f"- {symbol}: not tradable in Alpaca account, skipping.", log_file)
                    continue

                position_qty = get_position_qty(client, symbol)
                action, reason = symbol_action_from_investment_possibilities(symbol, position_qty, sess)
                bot_log(f"- {symbol}: action={action}, position={position_qty}, basis='{reason}'", log_file)

                if position_qty != 0:
                    unrealized_pl = get_unrealized_pl(client, symbol)
                    if unrealized_pl is not None and unrealized_pl < loss_close_threshold:
                        bot_log(
                            f"- {symbol}: unrealized P/L {unrealized_pl:.2f} < {loss_close_threshold:.2f}, "
                            "force-closing position to limit losses.",
                            log_file,
                        )
                        close_position(client, symbol, position_qty, log_file=log_file)
                        continue

                if action == "BUY" and position_qty == 0:
                    place_market_order(client, symbol, OrderSide.BUY, buy_qty, log_file=log_file)
                elif action == "CLOSE" and position_qty != 0:
                    close_position(client, symbol, position_qty, log_file=log_file)

            time.sleep(open_interval_seconds)

        except KeyboardInterrupt:
            cmd = input("\nBot interrupt detected. Type EXIT to stop bot, or press Enter to continue: ").strip().upper()
            if cmd == "EXIT":
                bot_log("Stopping bot by user request.", log_file)
                break
            bot_log("Continuing bot session.", log_file)
            continue
        except Exception as exc:
            bot_log(f"Bot error: {exc}", log_file)
            # Sleep briefly to avoid tight retry loop on API/network issues.
            time.sleep(30)


if __name__ == "__main__":
    run_bot()
