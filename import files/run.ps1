# Run the Stock Analysis Streamlit app (uses first available port 8501-8599)
# Double-click this file or run in PowerShell: .\run.ps1
Set-Location $PSScriptRoot
& .\venv\Scripts\python.exe app.py
Read-Host "Press Enter to close"
