# Google Cloud Storage Integration - Complete Setup Guide

## What Was Set Up

Your trading system now automatically uploads:
1. **Optimizer results** - After each backtest completes
2. **Trade logs** - When trading sessions end
3. **All results** - Persisted in Google Cloud Storage for history and analysis

---

## Installation (Do This First)

### 1. Install Python Dependency
```bash
pip install google-cloud-storage
```

Or update your environment:
```bash
pip install -r requirements.txt
```

### 2. Set Up GCP (One-time setup)

Follow the complete instructions in `GCP_SETUP.md`:
```bash
cat GCP_SETUP.md
```

Quick summary:
```bash
gcloud config set project t-infinity-333506
gsutil mb -l us gs://generative-ai-finance-backtest-logs
gcloud iam service-accounts create backtest-logger \
  --display-name="Backtest Logger Service Account"
gcloud iam service-accounts keys create gcp-key.json \
  --iam-account=backtest-logger@t-infinity-333506.iam.gserviceaccount.com
```

### 3. Store Credentials
Place `gcp-key.json` in your project root (it's already in `.gitignore`):
```bash
mv gcp-key.json /path/to/Generative_AI_Finance/gcp-key.json
```

### 4. Verify Setup
```bash
gsutil ls gs://generative-ai-finance-backtest-logs
```

Should return empty (bucket just created).

---

## How It Works

### Automatic Uploads

**When you run the optimizer:**
```bash
python "import files/optimize_nasdaq_for_alpaca.py" --symbol NVDA --mode paper
```

✓ Results automatically upload to:
- `gs://generative-ai-finance-backtest-logs/optimizer/NVDA/2026-01-15T10-30-00.123456/results.json`
- `gs://generative-ai-finance-backtest-logs/optimizer/NVDA/2026-01-15T10-30-00.123456/summary.json`

**When you stop the trading bot:**
```
Bot session ended. Type BACK to return...
```

✓ Log file automatically uploads to:
- `gs://generative-ai-finance-backtest-logs/trade-logs/alpaca_bot_paper_20260115_103000.log`

### Error Handling

If upload fails (no internet, bad credentials):
- ✓ Local storage still works (fallback)
- ✓ Warning printed to console `[GCS] Warning: ...`
- ✓ Execution continues normally

---

## Retrieving Your Logs

### List Recent Backtests
```bash
gsutil ls gs://generative-ai-finance-backtest-logs/optimizer/NVDA/
```

### Download Latest Results
```bash
gsutil cp gs://generative-ai-finance-backtest-logs/optimizer/NVDA/*/summary.json ./latest_nvda.json
```

### Download All Trade Logs
```bash
gsutil cp gs://generative-ai-finance-backtest-logs/trade-logs/alpaca_bot_paper_*.log ./
```

### View Logs Without Downloading
```bash
gsutil cat gs://generative-ai-finance-backtest-logs/trade-logs/alpaca_bot_paper_*.log | tail -100
```

**See `GCP_CLI_COMMANDS.md` for 30+ examples and advanced queries.**

---

## Files Modified

### New Files Created
1. **`gcp_utils.py`** - Google Cloud Storage utilities
   - `upload_to_gcs()` - Upload files
   - `upload_dataframe_as_json()` - Upload DataFrames
   - `get_gcs_client()` - Authenticate

2. **`GCP_SETUP.md`** - Complete setup instructions
3. **`GCP_CLI_COMMANDS.md`** - CLI commands for retrieval

### Files Modified
1. **`requirements.txt`** - Added `google-cloud-storage`
2. **`import files/optimize_nasdaq_for_alpaca.py`**
   - Added GCS import
   - Added `upload_results_to_gcs()` function
   - Calls upload after each optimization
   
3. **`alpaca_trading_bot.py`**
   - Added GCS import
   - Uploads log file when session ends

---

## Next Steps

### 1. Complete GCP Setup (5 min)
```bash
bash # Follow all commands in GCP_SETUP.md
```

### 2. Verify Installation (1 min)
```bash
python -c "import google.cloud.storage; print('✓ google-cloud-storage installed')"
gsutil ls gs://generative-ai-finance-backtest-logs
```

### 3. Test It
```bash
# Run a quick backtest
python "import files/optimize_nasdaq_for_alpaca.py" --symbol AAPL --mode paper --min-trades 1

# Should print: [GCS] ✓ Uploaded results to gs://...
```

### 4. Retrieve Logs
```bash
gsutil ls gs://generative-ai-finance-backtest-logs/optimizer/AAPL/
gsutil cp gs://generative-ai-finance-backtest-logs/optimizer/AAPL/*/summary.json ./
```

---

## Architecture

```
Your Code                GCP Integration            Google Cloud
─────────────           ─────────────             ────────────────
optimize.py  ──────→    upload_results_to_gcs()   ┌─────────────┐
                        ↓                          │   GCS       │
                        gcp_utils.py               │  Bucket:    │
                        ↓                          │  backtest   │
bot.py ──────→         upload_file_to_gcs()      │   -logs     │
                        ↓                          │             │
                        google-cloud-storage      │  /optimizer │
                        ↓                          │  /trade-logs│
                        HTTP → Google Cloud        └─────────────┘
```

---

## Fallback Mode

If credentials are missing or network fails:
```
[GCS] Warning: Cloud credentials not configured. Logs will be stored locally only.
```

✓ Results still saved locally in `/logs/`
✓ Everything works normally
✓ No impact on trading

---

## Troubleshooting

**Q: "ImportError: No module named 'google.cloud'"**
```bash
pip install google-cloud-storage
```

**Q: "Permission denied" when uploading**
```bash
export GOOGLE_APPLICATION_CREDENTIALS="./gcp-key.json"
python "import files/optimize_nasdaq_for_alpaca.py" --symbol NVDA --mode paper
```

**Q: Results aren't uploading**
- Check console for `[GCS]` messages
- Verify `gcp-key.json` exists in project root
- Run: `gsutil ls gs://generative-ai-finance-backtest-logs/` to confirm bucket exists

---

## Cost

- **First 1GB/month:** Free
- **After 1GB:** $0.020 per GB/month
- **Typical usage:** <1GB/year for millions of backtest runs

---

## Summary

You can now:
✓ Run backtests and automatically upload results  
✓ Trade and automatically upload logs  
✓ Retrieve any past result with one `gsutil` command  
✓ Analyze results across days/weeks/months  
✓ Fall back to local storage if cloud unavailable  

**Next:** Complete GCP_SETUP.md, then test with a single backtest!
