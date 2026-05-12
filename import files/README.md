# Stock Analysis

A Streamlit app for tracking portfolio performance from a CSV file, refreshing market prices from Yahoo Finance, and running common technical/fundamental stock checks.

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
  - Live write-ups using the same analytics engine
  - Latest prices for saved tickers
- CLI app for terminal usage

## Project Files

- `app.py`: Main Streamlit app
- `utils.py`: Data retrieval and analysis helpers
- `cli_app.py`: Interactive CLI version for terminal use
- `requirements.txt`: Python dependencies
- `run.ps1`: Windows helper script to launch the app with the local venv Python
- `app_minimal.py`: Minimal Streamlit smoke test
- `hello_world.py`: Basic Streamlit hello-world test
- `debug_app.py`: Import/debug script

## Requirements

- Python 3.10+
- Internet access (market data from Yahoo endpoints)

## Installation

```powershell
cd "c:\Users\ryan_\Documents\github\Generative_AI_Finance"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

### Option 1: Streamlit directly

```powershell
.\venv\Scripts\Activate.ps1
streamlit run app.py
```

### Option 2: PowerShell launcher script

```powershell
.\run.ps1
```

### Option 3: CLI (terminal)

```powershell
.\venv\Scripts\Activate.ps1
python cli_app.py
```

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

- Create a `.env` file at the repo root with `OPENAI_API_KEY=...` if you plan to use the AI features.
- Prices are converted to EUR using FX rates from Yahoo pairs.
- If a ticker cannot be priced, the app continues and marks that row as unavailable.
- Some analysis metrics may be unavailable for certain instruments (for example ETFs/crypto for P/E).
