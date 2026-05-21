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


def ask_bot_settings() -> tuple[int, int]:
    qty_text = input("Order quantity (default 1): ").strip() or "1"
    qty = int(qty_text)
    if qty <= 0:
        raise ValueError("Quantity must be a positive integer.")

    interval_text = input("Check interval in seconds while market is open (default 60): ").strip() or "60"
    interval_seconds = int(interval_text)
    if interval_seconds < 5:
        interval_seconds = 5

    return qty, interval_seconds


def get_position_qty(client: TradingClient, symbol: str) -> int:
    try:
        pos = client.get_open_position(symbol)
    except Exception:
        return 0

    try:
        return int(float(pos.qty))
    except Exception:
        return 0


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


def place_market_order(client: TradingClient, symbol: str, side: OrderSide, qty: int) -> None:
    req = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=side,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(order_data=req)
    print(f"[{datetime.now().isoformat(timespec='seconds')}] Placed {side.value} order: {order.id}")


def sleep_until_market_open(client: TradingClient) -> None:
    while True:
        clock = client.get_clock()
        if clock.is_open:
            print("Market is now open. Waking bot and resuming trading loop.")
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

        print(
            "Market closed. Sleeping until market opens. "
            f"Time until open: {hours}h {minutes}m | "
            f"Next open (ET): {next_open_et.strftime('%Y-%m-%d %I:%M %p %Z')} | "
            f"Local: {next_open_local.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )

        # Sleep in short chunks so we can keep the user updated.
        time.sleep(min(remaining, 60))


def run_bot(portfolio_tickers: list[str] | None = None) -> None:
    load_env_files()

    mode = ask_mode()
    api_key, api_secret, base_url = get_credentials(mode)
    buy_qty, open_interval_seconds = ask_bot_settings()

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
    print(
        f"Connected to Alpaca ({mode.upper()}). "
        f"Account status: {account.status}, buying power: {account.buying_power}"
    )
    print("Bot started for portfolio symbols:")
    print(", ".join(symbols))
    print("Decisions come from Investment Possibilities recommendations (Buy/Hold/Caution).")
    print("Actions: BUY, HOLD, CLOSE (close = sell full open position).")
    print("It will sleep when market is closed and wake when open.")
    print("Press Ctrl+C only if you want to request bot exit.")

    while True:
        try:
            clock = client.get_clock()

            if not clock.is_open:
                sleep_until_market_open(client)
                continue

            ts = datetime.now().isoformat(timespec="seconds")
            print(f"[{ts}] Market OPEN | scanning portfolio symbols...")

            for symbol in symbols:
                if not is_symbol_tradable(client, symbol):
                    print(f"- {symbol}: not tradable in Alpaca account, skipping.")
                    continue

                position_qty = get_position_qty(client, symbol)
                action, reason = symbol_action_from_investment_possibilities(symbol, position_qty, sess)
                print(f"- {symbol}: action={action}, position={position_qty}, basis='{reason}'")

                if action == "BUY" and position_qty == 0:
                    place_market_order(client, symbol, OrderSide.BUY, buy_qty)
                elif action == "CLOSE" and position_qty > 0:
                    place_market_order(client, symbol, OrderSide.SELL, position_qty)

            time.sleep(open_interval_seconds)

        except KeyboardInterrupt:
            cmd = input("\nBot interrupt detected. Type EXIT to stop bot, or press Enter to continue: ").strip().upper()
            if cmd == "EXIT":
                print("Stopping bot by user request.")
                break
            print("Continuing bot session.")
            continue
        except Exception as exc:
            print(f"Bot error: {exc}")
            # Sleep briefly to avoid tight retry loop on API/network issues.
            time.sleep(30)


if __name__ == "__main__":
    run_bot()
