# GCP Cloud Storage Setup for Backtest Logging

## Prerequisites
- Google Cloud project: `t-infinity-333506`
- `gcloud` CLI installed ([install here](https://cloud.google.com/sdk/docs/install))

## Setup Steps (Run in Terminal)

### 1. Set Your Project ID
```bash
gcloud config set project t-infinity-333506
```

### 2. Create Cloud Storage Bucket
```bash
gsutil mb -l us gs://generative-ai-finance-backtest-logs
```

### 3. Create Service Account
```bash
gcloud iam service-accounts create backtest-logger \
  --display-name="Backtest Logger Service Account"
```

### 4. Create and Download JSON Key
```bash
gcloud iam service-accounts keys create gcp-key.json \
  --iam-account=backtest-logger@t-infinity-333506.iam.gserviceaccount.com
```

**Output:** File `gcp-key.json` is created in your current directory. 
**Move it to your project root:**
```bash
mv gcp-key.json /path/to/Generative_AI_Finance/gcp-key.json
```

### 5. Grant Storage Permissions
```bash
gcloud projects add-iam-policy-binding t-infinity-333506 \
  --member=serviceAccount:backtest-logger@t-infinity-333506.iam.gserviceaccount.com \
  --role=roles/storage.objectCreator

gcloud projects add-iam-policy-binding t-infinity-333506 \
  --member=serviceAccount:backtest-logger@t-infinity-333506.iam.gserviceaccount.com \
  --role=roles/storage.objectViewer
```

### 6. Set Environment Variable (One-Time, for local testing)
```bash
# Linux/Mac
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/gcp-key.json"

# Windows (PowerShell)
$env:GOOGLE_APPLICATION_CREDENTIALS = "$(Get-Location)\gcp-key.json"

# Windows (cmd)
set GOOGLE_APPLICATION_CREDENTIALS=%cd%\gcp-key.json
```

### 7. Verify Setup
```bash
gsutil ls gs://generative-ai-finance-backtest-logs
```
Should return empty (bucket just created).

---

## Adding to Your Project

### 1. Add to .gitignore
```bash
echo "gcp-key.json" >> .gitignore
```

### 2. Update .env (Optional - for CI/CD)
You can add this line to `.import files/.env`:
```
GOOGLE_APPLICATION_CREDENTIALS=./gcp-key.json
```

### 3. Install Python Dependency
```bash
pip install google-cloud-storage
```

---

## Verify Everything Works
After the code changes are made, run:
```bash
# Optimizer will auto-upload results
python "import files/optimize_nasdaq_for_alpaca.py" --symbol NVDA --mode paper

# Check if results uploaded
gsutil ls gs://generative-ai-finance-backtest-logs/optimizer/
```

---

## Troubleshooting

**Permission Denied Error:**
```bash
# Ensure you're using the right credentials
gcloud auth application-default login
# OR set the env var
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/gcp-key.json"
```

**Bucket Already Exists:**
```bash
# If bucket exists, skip creation and just use it
gsutil ls gs://generative-ai-finance-backtest-logs
```

**Service Account Not Found:**
Make sure you used the right project ID (`t-infinity-333506`)
