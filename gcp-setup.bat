@echo off
REM GCP Setup Script for Generative AI Finance (Windows)
REM Copy and paste this entire script into Command Prompt or PowerShell

setlocal enabledelayedexpansion

echo ================================================
echo GCP Cloud Storage Setup for Backtest Logging
echo ================================================
echo.
echo Project ID: t-infinity-333506
echo.

REM Step 1
echo Step 1: Setting project...
call gcloud config set project t-infinity-333506
echo [OK] Project set
echo.

REM Step 2
echo Step 2: Creating Cloud Storage bucket...
call gsutil mb -l us gs://generative-ai-finance-backtest-logs
if errorlevel 1 echo [INFO] Bucket already exists
echo [OK] Bucket ready
echo.

REM Step 3
echo Step 3: Creating service account...
call gcloud iam service-accounts create backtest-logger --display-name="Backtest Logger Service Account"
if errorlevel 1 echo [INFO] Service account already exists
echo [OK] Service account ready
echo.

REM Step 4
echo Step 4: Creating and downloading JSON key...
call gcloud iam service-accounts keys create gcp-key.json --iam-account=backtest-logger@t-infinity-333506.iam.gserviceaccount.com
echo [OK] Key file created: gcp-key.json
echo.

REM Step 5
echo Step 5: Granting storage permissions...
call gcloud projects add-iam-policy-binding t-infinity-333506 --member=serviceAccount:backtest-logger@t-infinity-333506.iam.gserviceaccount.com --role=roles/storage.objectCreator
if errorlevel 1 echo [INFO] Permission already set

call gcloud projects add-iam-policy-binding t-infinity-333506 --member=serviceAccount:backtest-logger@t-infinity-333506.iam.gserviceaccount.com --role=roles/storage.objectViewer
if errorlevel 1 echo [INFO] Permission already set
echo [OK] Permissions granted
echo.

REM Step 6
echo Step 6: Adding to .gitignore...
findstr /M "gcp-key.json" .gitignore >nul 2>&1
if errorlevel 1 (
  echo gcp-key.json >> .gitignore
  echo [OK] Added to .gitignore
) else (
  echo [INFO] Already in .gitignore
)
echo.

REM Step 7
echo Step 7: Verifying setup...
set GOOGLE_APPLICATION_CREDENTIALS=%cd%\gcp-key.json
call gsutil ls gs://generative-ai-finance-backtest-logs
echo [OK] Setup verified!
echo.

echo ================================================
echo [OK] GCP Setup Complete!
echo ================================================
echo.
echo Next steps:
echo 1. Install Python: pip install google-cloud-storage
echo 2. Test optimizer: python "import files/optimize_nasdaq_for_alpaca.py" --symbol AAPL --mode paper --min-trades 1
echo 3. Check results: gsutil ls gs://generative-ai-finance-backtest-logs/optimizer/AAPL/
echo.
echo Your credentials: gcp-key.json (ignored by git)
echo.

pause
