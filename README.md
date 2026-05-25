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
- AI recommendations tab:
  - Volatility, P/E, beta, Sharpe, and MACD summaries
  - Explanations for how to interpret each metric
- Investment possibilities tab:
  - Add candidate tickers
  - Live per-instrument write-ups using the same analytics engine
  - Latest prices for saved tickers
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

Common mistakes to avoid:

- Do not run `python cli_app.py` from `.venv` (Python 3.14).
- Do not run `python run_cli.sh`; run `bash ./run_cli.sh`.

## Alpaca Trading Bot (CLI Option 8)

From `python cli_app.py`, choose:

- `8. Alpaca Trading Bot`

Behavior:

- Prompts for paper or live mode
- Loads all portfolio tickers from the current CSV session
- Uses Investment Possibilities-style recommendations to map actions
  - `Buy` -> `BUY`
  - `Hold` -> `HOLD`
  - `Caution/No action` -> `CLOSE` (if position exists)
- Checks market clock and only trades when open
- Prints sleep/wake status and time until next market open when closed

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
