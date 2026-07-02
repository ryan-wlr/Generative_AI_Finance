# Copy-Paste Commands for GCP Setup

## For Linux/Mac Users
Copy and paste each command one at a time:

```
gcloud config set project t-infinity-333506
```

```
gsutil mb -l us gs://generative-ai-finance-backtest-logs
```

```
gcloud iam service-accounts create backtest-logger --display-name="Backtest Logger Service Account"
```

```
gcloud iam service-accounts keys create gcp-key.json --iam-account=backtest-logger@t-infinity-333506.iam.gserviceaccount.com
```

```
gcloud projects add-iam-policy-binding t-infinity-333506 --member=serviceAccount:backtest-logger@t-infinity-333506.iam.gserviceaccount.com --role=roles/storage.objectCreator
```

```
gcloud projects add-iam-policy-binding t-infinity-333506 --member=serviceAccount:backtest-logger@t-infinity-333506.iam.gserviceaccount.com --role=roles/storage.objectViewer
```

```
echo "gcp-key.json" >> .gitignore
```

```
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/gcp-key.json"
```

```
gsutil ls gs://generative-ai-finance-backtest-logs
```

---

## For Windows Users (PowerShell)
Copy and paste each command one at a time:

```
gcloud config set project t-infinity-333506
```

```
gsutil mb -l us gs://generative-ai-finance-backtest-logs
```

```
gcloud iam service-accounts create backtest-logger --display-name="Backtest Logger Service Account"
```

```
gcloud iam service-accounts keys create gcp-key.json --iam-account=backtest-logger@t-infinity-333506.iam.gserviceaccount.com
```

```
gcloud projects add-iam-policy-binding t-infinity-333506 --member=serviceAccount:backtest-logger@t-infinity-333506.iam.gserviceaccount.com --role=roles/storage.objectCreator
```

```
gcloud projects add-iam-policy-binding t-infinity-333506 --member=serviceAccount:backtest-logger@t-infinity-333506.iam.gserviceaccount.com --role=roles/storage.objectViewer
```

```
Add-Content -Path ".gitignore" -Value "gcp-key.json"
```

```
$env:GOOGLE_APPLICATION_CREDENTIALS = "$PWD\gcp-key.json"
```

```
gsutil ls gs://generative-ai-finance-backtest-logs
```

---

## Or Use Automated Script

**Linux/Mac:**
```
bash gcp-setup.sh
```

**Windows:**
```
gcp-setup.bat
```

---

## After Setup: Copy-Paste Commands for Daily Use

### Install Python dependency
```
pip install google-cloud-storage
```

### Run optimizer (test)
```
python "import files/optimize_nasdaq_for_alpaca.py" --symbol AAPL --mode paper --min-trades 1
```

### List all backtest runs
```
gsutil ls gs://generative-ai-finance-backtest-logs/optimizer/
```

### Download latest NVDA backtest
```
gsutil cp gs://generative-ai-finance-backtest-logs/optimizer/NVDA/*/summary.json ./latest_nvda.json
```

### Download all paper trade logs
```
gsutil cp gs://generative-ai-finance-backtest-logs/trade-logs/alpaca_bot_paper_*.log ./
```

### View latest logs (no download)
```
gsutil cat gs://generative-ai-finance-backtest-logs/trade-logs/alpaca_bot_paper_*.log | tail -50
```

### Search for BUY trades in logs
```
gsutil cat gs://generative-ai-finance-backtest-logs/trade-logs/alpaca_bot_paper_*.log | grep "BUY"
```

### Download all results for today
```
gsutil cp -r gs://generative-ai-finance-backtest-logs/optimizer/*/2026-01-15*/ ./today_results/
```

---

## If Something Goes Wrong

### Verify credentials file exists
```
ls gcp-key.json
```

### Set credentials (if upload fails)
```
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/gcp-key.json"
```

### Test credentials
```
gsutil ls gs://generative-ai-finance-backtest-logs
```

### Check if bucket exists
```
gsutil ls
```

### Re-authenticate with Google
```
gcloud auth application-default login
```
