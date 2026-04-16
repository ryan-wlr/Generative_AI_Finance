# Generative_AI_Finance

Generative_AI_Finance is a Streamlit-based portfolio analysis app for personal finance tracking. It lets you upload a holdings CSV, fetch current market prices from Yahoo Finance, calculate gains in EUR, update positions, export refreshed portfolio data, and view simple stock analysis charts such as moving averages.

## What the app does

- Uploads a portfolio CSV and validates the expected finance columns.
- Pulls live or recent market prices for your tickers using Yahoo Finance.
- Converts prices to EUR using foreign exchange rates when needed.
- Calculates:
	- current value of each holding
	- gain since the last portfolio update
	- gain since purchase
	- portfolio-level totals
- Lets you record position changes by updating units and purchase price.
- Lets you add new assets to the portfolio.
- Exports the updated portfolio back to CSV.
- Shows basic stock analysis with moving average charts.

## Expected CSV columns

Your input CSV should contain these columns:

- Asset
- Ticker
- Currency Yahoo
- Units
- Purchase Price
- Value Last Update

Example tickers should use Yahoo Finance symbols such as `AAPL`, `MSFT`, `GOOGL`, `BTC-EUR`, or `ETH-USD`.

## Requirements

- Python 3.10+
- Internet access for Yahoo Finance market data

Install dependencies with:

```bash
pip install -r requirements.txt
```

## How to run

From the `Generative_AI_Finance` folder, start the main app with:

```bash
streamlit run app.py
```

If you are using the included Windows PowerShell launcher, run:

```powershell
.\run.ps1
```

Then open the local Streamlit URL shown in the terminal, usually:

```text
http://localhost:8501
```

## Other helper apps

- `app_minimal.py`: minimal upload screen for quick Streamlit validation
- `hello_world.py`: basic Streamlit sanity check
- `debug_app.py`: import-by-import debugging script

## Typical workflow

1. Launch the app.
2. Upload your portfolio CSV.
3. Click `Load current prices` to fetch market data.
4. Review gains and totals in the `Gains` tab.
5. Update holdings or add assets in `Stock Updates`.
6. Download the refreshed CSV from `Export Data`.
7. Use `Stock Analysis` to inspect moving averages.

## Notes

- The app currently standardizes portfolio calculations in EUR.
- Price availability depends on Yahoo Finance symbol support.
- If a ticker cannot be resolved, the app will keep other supported tickers loaded and report which ones failed.
