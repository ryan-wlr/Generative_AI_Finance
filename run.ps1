# Run the Stock Analysis Streamlit app (uses first available port 8501-8599)
# Double-click this file or run in PowerShell: .\run.ps1
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv311\Scripts\python.exe"
if (-not (Test-Path $python)) {
	Write-Error ".venv311 not found. Create it first with: py -3.11 -m venv .venv311"
	exit 1
}

& $python -m streamlit run app.py
Read-Host "Press Enter to close"
