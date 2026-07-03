# CLI Commands to Retrieve Backtest Logs from Google Cloud Storage

## VM to Local Computer (Direct Copy)

Use these when your logs are on the VM and you want them on your own laptop/desktop.

### Option A: Linux/macOS local terminal

```bash
# From your LOCAL machine (not inside SSH)
bash pull_vm_logs_to_local.sh us-central1-a

# With explicit values
bash pull_vm_logs_to_local.sh us-central1-a instance-20260521-042726 weilerryan31 /home/weilerryan31/Generative_AI_Finance "$HOME/Downloads/finance-logs"

# If IAP is required
USE_IAP=1 bash pull_vm_logs_to_local.sh us-central1-a
```

### Option B: Windows PowerShell local terminal

```powershell
# From your LOCAL machine (not inside SSH)
.\pull_vm_logs_to_local.ps1 -Zone us-central1-a

# With explicit values
.\pull_vm_logs_to_local.ps1 -Zone us-central1-a -Instance instance-20260521-042726 -VmUser weilerryan31 -RemoteDir /home/weilerryan31/Generative_AI_Finance -DestDir "$HOME\Downloads\finance-logs"

# If IAP is required
.\pull_vm_logs_to_local.ps1 -Zone us-central1-a -UseIap
```

### Find your zone (run locally)

```bash
gcloud compute instances list --filter="name=instance-20260521-042726"
```

### Verify downloaded files (local)

```bash
ls -lh ~/Downloads/finance-logs/*.log
```

## Quick Start

### 1. List All Backtest Optimization Results
```bash
# List all symbols that have been optimized
gsutil ls gs://generative-ai-finance-backtest-logs/optimizer/

# List all optimization runs for a specific symbol
gsutil ls gs://generative-ai-finance-backtest-logs/optimizer/NVDA/
```

### 2. Download Latest Backtest Results
```bash
# Download the most recent NVDA optimization results
gsutil cp gs://generative-ai-finance-backtest-logs/optimizer/NVDA/*/summary.json ./nvda_latest_summary.json

# Download all results for a symbol (full DataFrame)
gsutil cp gs://generative-ai-finance-backtest-logs/optimizer/NVDA/*/results.json ./nvda_latest_results.json
```

### 3. Download All Trade Logs
```bash
# List all trade logs
gsutil ls gs://generative-ai-finance-backtest-logs/trade-logs/

# Download a specific trade session log
gsutil cp gs://generative-ai-finance-backtest-logs/trade-logs/alpaca_bot_paper_20260101_120000.log ./

# Download all paper trading logs
gsutil cp gs://generative-ai-finance-backtest-logs/trade-logs/alpaca_bot_paper_*.log ./local_logs/

# Download all live trading logs
gsutil cp gs://generative-ai-finance-backtest-logs/trade-logs/alpaca_bot_live_*.log ./local_logs/
```

### 4. View Logs Without Downloading
```bash
# Print latest trade log to console
gsutil cat gs://generative-ai-finance-backtest-logs/trade-logs/alpaca_bot_paper_*.log | tail -100

# Search for specific trades in logs
gsutil cat gs://generative-ai-finance-backtest-logs/trade-logs/alpaca_bot_paper_*.log | grep "BUY"

# Count total trades across all sessions
gsutil cat gs://generative-ai-finance-backtest-logs/trade-logs/alpaca_bot_paper_*.log | grep -c "Placed.*order"
```

---

## Advanced Usage

### Analyze Backtest Results

```bash
# Download results and analyze locally with Python
gsutil cp gs://generative-ai-finance-backtest-logs/optimizer/NVDA/*/summary.json ./results.json

# Then analyze in Python:
python -c "
import json
with open('results.json') as f:
    data = json.load(f)
print(f\"Symbol: {data['symbol']}\")
print(f\"Latest Signal: {data['latest_signal']}\")
print(f\"Test Return: {data['best_metrics']['test_return']*100:.2f}%\")
print(f\"Test Sharpe: {data['best_metrics']['test_sharpe']:.2f}\")
print(f\"Test Trades: {data['best_metrics']['test_trades']}\")
"
```

### Compare Multiple Symbols

```bash
# Download all summaries from today
gsutil cp gs://generative-ai-finance-backtest-logs/optimizer/*/2026-01-15*/summary.json ./

# Compare returns across symbols
for file in summary.json; do
  echo "=== $file ==="
  grep -oP '"symbol": "\K[^"]+|"test_return": \K[0-9.-]+' $file
done
```

### Archive and Backup

```bash
# Download entire backtest history (all symbols, all dates)
gsutil -m cp -r gs://generative-ai-finance-backtest-logs/optimizer/ ./local_backups/

# Download only this month's results
gsutil -m cp -r gs://generative-ai-finance-backtest-logs/optimizer/*/2026-01*/ ./january_2026_results/

# Create a local archive
gsutil -m cp -r gs://generative-ai-finance-backtest-logs/ ./full_backup_$(date +%Y%m%d).tar.gz
```

### Monitor Recent Activity

```bash
# Show optimization runs from the last 24 hours
gsutil ls -L gs://generative-ai-finance-backtest-logs/optimizer/ | grep "Time created"

# Watch for new backtest uploads (requires gsutil beta)
gsutil -m ls -rh gs://generative-ai-finance-backtest-logs/ | sort -k2 | tail -20
```

---

## Using Python to Parse Results

```python
import json
from pathlib import Path
from google.cloud import storage

def get_latest_backtest(symbol):
    """Download and parse latest backtest results for a symbol."""
    client = storage.Client(project="t-infinity-333506")
    bucket = client.bucket("generative-ai-finance-backtest-logs")
    
    # List all results for this symbol
    blobs = bucket.list_blobs(prefix=f"optimizer/{symbol}/")
    
    # Find the most recent summary.json
    summaries = [b.name for b in blobs if b.name.endswith("summary.json")]
    if not summaries:
        print(f"No results found for {symbol}")
        return None
    
    latest = sorted(summaries)[-1]
    blob = bucket.blob(latest)
    content = blob.download_as_text()
    return json.loads(content)

# Example usage
results = get_latest_backtest("NVDA")
if results:
    print(f"Latest NVDA signal: {results['latest_signal']}")
    print(f"Test return: {results['best_metrics']['test_return']*100:.2f}%")
    print(f"Parameters: {results['best_parameters']}")
```

---

## Troubleshooting

### "Permission denied" Error
```bash
# Ensure you have credentials
gcloud auth application-default login

# Or set credentials file
export GOOGLE_APPLICATION_CREDENTIALS="./gcp-key.json"
```

### "No such object" Error
```bash
# Bucket name must be correct and exact
gsutil ls gs://generative-ai-finance-backtest-logs/

# Check if optimizer actually uploaded (may skip on error)
# Look for [GCS] messages in console output
```

### Large Downloads Timing Out
```bash
# Use parallel download with -m flag
gsutil -m cp -r gs://generative-ai-finance-backtest-logs/optimizer/ ./backup/

# Or download by symbol
gsutil cp gs://generative-ai-finance-backtest-logs/optimizer/NVDA/*/summary.json ./
```

---

## Automated Retrieval Script

Save as `download_backtest_results.sh`:

```bash
#!/bin/bash

SYMBOL=${1:-NVDA}
DEST=${2:-.}

echo "Downloading latest backtest for $SYMBOL..."
gsutil cp gs://generative-ai-finance-backtest-logs/optimizer/$SYMBOL/*/summary.json "$DEST/latest_${SYMBOL}_summary.json"
gsutil cp gs://generative-ai-finance-backtest-logs/optimizer/$SYMBOL/*/results.json "$DEST/latest_${SYMBOL}_results.json"

echo "✓ Downloaded to $DEST"
ls -lh "$DEST/"latest_*
```

Usage:
```bash
chmod +x download_backtest_results.sh
./download_backtest_results.sh NVDA ./my_results
./download_backtest_results.sh AAPL ./my_results
```
