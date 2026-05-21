# PowerShell launcher for CLI using the Python 3.11 environment.
# Usage: .\run_cli.ps1

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv311\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating .venv311 with py -3.11 ..."
    py -3.11 -m venv .venv311
}

& $python -m pip install -r requirements.txt
& $python cli_app.py
