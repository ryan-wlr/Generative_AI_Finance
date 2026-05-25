# PowerShell launcher for CLI using the Python 3.11 environment.
# Usage: .\run_cli.ps1

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv311\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host ".venv311 not found. Creating with Python 3.11..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3.11 -m venv .venv311
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        python -m venv .venv311
    }
    else {
        Write-Error "Could not find 'py' or 'python' on PATH. Install Python 3.11 and retry."
        exit 1
    }
    if (-not (Test-Path $python)) {
        Write-Error "Failed to create .venv311 at $python"
        exit 1
    }
}

& $python -m pip install -r requirements.txt
& $python cli_app.py
