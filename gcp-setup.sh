#!/bin/bash

# GCP Setup Script for Generative AI Finance
# Copy and paste this entire script into your terminal to set up Google Cloud Storage

set -e  # Exit on error

echo "================================================"
echo "GCP Cloud Storage Setup for Backtest Logging"
echo "================================================"
echo ""
echo "Project ID: t-infinity-333506"
echo ""

# Step 1
echo "Step 1: Setting project..."
gcloud config set project t-infinity-333506
echo "✓ Project set"
echo ""

# Step 2
echo "Step 2: Creating Cloud Storage bucket..."
gsutil mb -l us gs://generative-ai-finance-backtest-logs || echo "ℹ Bucket already exists"
echo "✓ Bucket ready"
echo ""

# Step 3
echo "Step 3: Creating service account..."
gcloud iam service-accounts create backtest-logger \
  --display-name="Backtest Logger Service Account" || echo "ℹ Service account already exists"
echo "✓ Service account ready"
echo ""

# Step 4
echo "Step 4: Creating and downloading JSON key..."
gcloud iam service-accounts keys create gcp-key.json \
  --iam-account=backtest-logger@t-infinity-333506.iam.gserviceaccount.com
echo "✓ Key file created: gcp-key.json"
echo ""

# Step 5
echo "Step 5: Granting storage permissions..."
gcloud projects add-iam-policy-binding t-infinity-333506 \
  --member=serviceAccount:backtest-logger@t-infinity-333506.iam.gserviceaccount.com \
  --role=roles/storage.objectCreator || echo "ℹ Permission already set"

gcloud projects add-iam-policy-binding t-infinity-333506 \
  --member=serviceAccount:backtest-logger@t-infinity-333506.iam.gserviceaccount.com \
  --role=roles/storage.objectViewer || echo "ℹ Permission already set"
echo "✓ Permissions granted"
echo ""

# Step 6
echo "Step 6: Adding to .gitignore..."
if grep -q "gcp-key.json" .gitignore 2>/dev/null; then
  echo "ℹ Already in .gitignore"
else
  echo "gcp-key.json" >> .gitignore
  echo "✓ Added to .gitignore"
fi
echo ""

# Step 7
echo "Step 7: Verifying setup..."
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/gcp-key.json"
gsutil ls gs://generative-ai-finance-backtest-logs
echo "✓ Setup verified!"
echo ""

echo "================================================"
echo "✓ GCP Setup Complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo "1. Install Python dependency: pip install google-cloud-storage"
echo "2. Run optimizer to test: python 'import files/optimize_nasdaq_for_alpaca.py' --symbol AAPL --mode paper --min-trades 1"
echo "3. Retrieve results: gsutil ls gs://generative-ai-finance-backtest-logs/optimizer/AAPL/"
echo ""
echo "Your credentials file: gcp-key.json (already ignored by git)"
