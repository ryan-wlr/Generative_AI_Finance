# Stock Analysis

A Streamlit + CLI toolkit for portfolio tracking, market analysis, AI-style instrument assessment, and Alpaca trading-bot execution.

The project supports:

- Interactive Streamlit analysis in `app.py`
- Terminal workflow in `cli_app.py`
- Investment Possibilities assessments with portfolio-wide notes
- Alpaca paper/live bot mode from the CLI menu
- Automated security scans and dependency update checks via GitHub Actions

## Features

- Portfolio gains in EUR:
  - Gain since last update (EUR and %)
  - Gain since purchase (EUR and %)
  - Portfolio total row with aggregate return
- Portfolio updates:
  - Update units and average purchase price for existing assets
  - Add new assets by Yahoo ticker
- CSV export with latest calculated fields
- Stock analysis tab:
  - Moving averages (MA50, MA100, MA200)
  - Volatility (rolling annualized)
  - P/E ratio (trailing, positive earnings only)
  - Beta
  - Sharpe ratio
  - RSI
  - MACD
  - Selection 8 strategy: MACD + CMF + EMA + Supertrend (TradeSmart-style signal logic)
- AI recommendations tab:
  - Volatility, P/E, beta, Sharpe, and MACD summaries
  - Explanations for how to interpret each metric
- Investment possibilities tab:
  - Add candidate tickers
  - Live per-instrument write-ups using the same analytics engine
  - Latest prices for saved tickers
  - Selection 8 paper-trade signal logs per candidate ticker
  - Alpaca execution panel (paper/live) for Selection 8 signals
  - Portfolio analysis table for holdings and candidates
  - Overall portfolio note (heuristic/AI-style synthesis)
- CLI app for terminal usage
- CLI trading menu option:
  - Alpaca bot mode (`paper` or `live`)
  - Uses all portfolio tickers automatically (no manual ticker entry)
  - Trades only during market hours
  - Sleeps while market is closed and displays time until open

## Project Files

- `app.py`: Main Streamlit app
- `utils.py`: Data retrieval and analysis helpers
- `cli_app.py`: Interactive CLI version for terminal use
- `alpaca_trading_bot.py`: Alpaca execution loop used by CLI option 8
- `requirements.txt`: Python dependencies
- `run.ps1`: Windows helper script to launch the app with the local venv Python
- `run_cli.ps1`: Windows helper script for CLI in the `.venv311` environment
- `run_cli.sh`: Git Bash helper script for CLI in the `.venv311` environment
- `run_cloud.sh`: Bash/cloud helper script for Streamlit deployment
- `app_minimal.py`: Minimal Streamlit smoke test
- `hello_world.py`: Basic Streamlit hello-world test
- `debug_app.py`: Import/debug script

## Requirements

- Python 3.10+
- Internet access (market data from Yahoo endpoints)

## Installation

```powershell
cd "c:\Users\ryan_\Documents\github\Generative_AI_Finance"
python -m venv .venv311
.\.venv311\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

Use the Python 3.11 environment (`.venv311`) for this project.

### Option 1: Streamlit directly

```powershell
.\.venv311\Scripts\python.exe -m streamlit run app.py
```

### Option 2: PowerShell launcher script

```powershell
.\run.ps1
```

### Option 3: CLI (terminal)

```powershell
.\.venv311\Scripts\python.exe cli_app.py
```

### Option 4: CLI helper script (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File .\run_cli.ps1
```

### Option 5: Bash/cloud helper script

```bash
PORT=8501 bash ./run_cloud.sh
```

### Option 6: CLI helper script (Git Bash)

```bash
bash ./run_cli.sh
```

### Option 7: CLI on Google Cloud VM (Ubuntu)

```bash
cd ~/Generative_AI_Finance
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip
sed -i 's/\r$//' ./run_cli.sh
chmod +x ./run_cli.sh
bash ./run_cli.sh
```

If you get permission issues, run:

```bash
/bin/bash ./run_cli.sh
```

Common mistakes to avoid:

- Do not run `python cli_app.py` from `.venv` (Python 3.14).
- Do not run `python run_cli.sh`; run `bash ./run_cli.sh`.

## Alpaca Trading Bot (CLI Option 8)

From `python cli_app.py`, choose:

- `8. Alpaca Trading Bot`

Behavior:

- Prompts for paper or live mode
- Prompts for startup settings:
  - Check interval while market is open (default: 15 seconds)
  - End-of-day force-close window (minutes before close)
  - Unrealized P/L loss-close threshold
  - Peak unrealized drawdown-close threshold
  - Entry mode: `relaxed`, `normal`, or `strict`
- Loads all portfolio tickers from the current CSV session
- Uses Investment Possibilities-style recommendations to map actions
  - `Buy` -> `BUY`
  - `Hold / accumulate` -> `BUY` (in `normal` and `relaxed` when no position exists)
  - `Hold` -> `BUY` only in `relaxed` when no position exists, otherwise `HOLD`
  - `Caution/No action` -> `CLOSE` (if position exists)
- Checks market clock and only trades when open
- Prints sleep/wake status and time until next market open when closed
- Caps scan sleep so it does not oversleep past the end-of-day close window
- End-of-day close is best-effort with per-symbol retries so one API/order error does not skip other symbols
- Exits open positions early when risk rules are breached:
  - Unrealized P/L below your loss threshold
  - Unrealized P/L drops from its session peak by at least your drawdown threshold

## Nasdaq Strategy Optimization For Alpaca

Use the optimizer script to tune TradeSmart-like parameters on one or many Alpaca-tradable symbols.

Script location:

- `import files/optimize_nasdaq_for_alpaca.py`

What it does:

- Verifies the symbol is tradable in your Alpaca account (`paper` or `live` mode)
- Pulls historical bars (default: `1h`, `730d`)
- Runs a parameter grid search for EMA/CMF/MACD/Supertrend
- Optimizer type: brute-force grid search (parameter sweep), not a neural-network optimizer like Adam/SGD
- Selects best parameters on train split and reports out-of-sample test metrics
- Computes companion strategy signals (MA, RSI, MACD)
- Optionally executes a trade using a vote threshold across:
  - optimizer signal
  - MA signal
  - RSI signal
  - MACD signal
- Adds a pre-buy quality gate for bullish entries, combining:
  - max trailing P/E threshold
  - max annualized volatility threshold
  - minimum bullish companion votes (MA/RSI/MACD)
- If bullish quality checks fail, execution is downgraded to `Neutral` (no buy order)
- Optional post-trade risk monitoring:
  - closes open position when unrealized P/L drops below your configured threshold
  - configurable risk-check interval (seconds)
  - optional force-close near end of trading day
- Supports market-open gating:
  - Skip run when market is closed (default)
  - Wait until market opens and run immediately (`--wait-for-open`)
  - Bypass gate and run even when closed (`--allow-when-closed`)

Run example (default Nasdaq symbol `NVDA`):

```powershell
.\.venv311\Scripts\python.exe "import files\optimize_nasdaq_for_alpaca.py" --symbol NVDA --mode paper
```

Try another Nasdaq symbol:

```powershell
.\.venv311\Scripts\python.exe "import files\optimize_nasdaq_for_alpaca.py" --symbol AAPL --mode paper --interval 1h --period 730d
```

Run with execution enabled and signal-vote threshold:

```powershell
.\.venv311\Scripts\python.exe "import files\optimize_nasdaq_for_alpaca.py" --symbol NVDA --mode paper --execute-trade --order-qty 1 --min-aligned-signals 2
```

Allow short entries on bearish signals:

```powershell
.\.venv311\Scripts\python.exe "import files\optimize_nasdaq_for_alpaca.py" --symbol NVDA --mode paper --execute-trade --allow-short-entries
```

Wait until next market open and run immediately:

```powershell
.\.venv311\Scripts\python.exe "import files\optimize_nasdaq_for_alpaca.py" --symbol NVDA --mode paper --wait-for-open
```

Run even when market is closed:

```powershell
.\.venv311\Scripts\python.exe "import files\optimize_nasdaq_for_alpaca.py" --symbol NVDA --mode paper --allow-when-closed
```

Run with explicit bullish quality-gate thresholds:

```powershell
.\.venv311\Scripts\python.exe "import files\optimize_nasdaq_for_alpaca.py" --symbol NVDA --mode paper --execute-trade --max-pe-ratio 40 --max-volatility-pct 55 --min-companion-bull-votes 2
```

### CLI menu option

From `python cli_app.py`, choose:

- `9. Nasdaq Strategy Optimization (Alpaca)`

Behavior in option 9:

- Symbol source menu:
  - `1` Tech presets
  - `2` Curated defense universe
  - `3` Portfolio tickers from loaded CSV
  - `4` Custom comma-separated tickers
  - `10` ALL sources at once (`1 + 2 + 3 + optional custom`)
- Deduplicates candidates, then optionally ranks and auto-picks top N symbols for that run
- Ranking is based on a composite score using:
  - 3-month momentum
  - 1-month momentum
  - Sharpe approximation
  - dollar-volume liquidity
  - volatility penalty
- Executes optimization in batch across selected symbols and prints success/failure summary per run
- Prompts for mode, interval, period, min trades, and cost bps
- Optional live/paper trade execution prompt
- Optional short-entry enable prompt
- Prompt for minimum aligned signals to trade
- Prompt for bullish pre-buy quality thresholds (max P/E, max volatility, minimum companion bullish votes)
- In source option `10`, strict alignment is enforced automatically for BUY decisions:
  - optimizer + MA + RSI + MACD must all align bullish
  - Supertrend, Chandelier Exit, and Trend Filter must all be bullish
- In source option `10`, end-of-day close is enforced automatically when execution is enabled
  - you still choose how many minutes before market close to force-close
- Prompt for auto-rerun every N minutes
- In source option `10`, continuous mode is enforced and rerun defaults to every 5 minutes if `0` is entered
- Prompt to wait for market open when closed
- Stays in optimizer flow until you explicitly type `BACK`
- Runs repeatedly and can be stopped with `Ctrl+C` (then choose `BACK` or reconfigure)

Important:

- Results are educational backtests, not guaranteed future returns.
- Always validate out-of-sample metrics and paper trade before live execution.

## Selection 8 Strategy Trading (Streamlit)

In the Streamlit app, go to:

- `Stock analysis` -> `MACD+CMF+EMA+Supertrend` (Selection 8)

This tab computes TradeSmart-style signal components and shows:

- Current strategy signal (`Bullish`, `Bearish`, `Neutral`)
- Most recent trigger direction/date
- Diagnostic charts (price + EMA + supertrend, MACD panel, CMF panel)

To place broker orders from these signals:

- Open `Investment Possibilities`
- Click `Generate strategy trades`
- Use `Alpaca execution (paper/live)`
- Choose mode (`paper` or `live`), quantity, and optional shorting
- Click `Execute strategy on Alpaca`

Safety behavior:

- `live` mode requires typed confirmation (`LIVE`)
- Symbol tradability is checked before order submission
- Default execution is long-only unless shorting is explicitly enabled

## CSV Input Format

Your uploaded CSV must include these columns (exact names after trimming spaces):

- `Asset`
- `Ticker`
- `Currency Yahoo`
- `Units`
- `Purchase Price`
- `Value Last Update`

`Ticker` values must be valid Yahoo Finance symbols (for example: `AAPL`, `MSFT`, `GOOGL`, `BTC-EUR`).

## Notes

- Create a `.env` file at the repo root (or in `import files/.env`) with values you need.

Example keys:

```env
OPENAI_API_KEY=...

ALPACA_PAPER_API_KEY=...
ALPACA_PAPER_API_SECRET=...
ALPACA_PAPER_BASE_URL=https://paper-api.alpaca.markets

ALPACA_LIVE_API_KEY=...
ALPACA_LIVE_API_SECRET=...
ALPACA_LIVE_BASE_URL=https://api.alpaca.markets
```

- Prices are converted to EUR using FX rates from Yahoo pairs.
- If a ticker cannot be priced, the app continues and marks that row as unavailable.
- Some analysis metrics may be unavailable for certain instruments (for example ETFs/crypto for P/E).
- Keep `.env` out of Git commits.

## Security

- See `SECURITY.md` for Google Cloud hardening guidance.
- GitHub Actions security scans run on push and pull request.
- Dependabot proposes weekly dependency update PRs.
