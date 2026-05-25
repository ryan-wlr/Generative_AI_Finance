#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

WIN_PYTHON_EXE="$SCRIPT_DIR/.venv311/Scripts/python.exe"
LINUX_PYTHON_EXE="$SCRIPT_DIR/.venv311/bin/python"

if [[ -x "$WIN_PYTHON_EXE" ]]; then
  PYTHON_EXE="$WIN_PYTHON_EXE"
elif [[ -x "$LINUX_PYTHON_EXE" ]]; then
  PYTHON_EXE="$LINUX_PYTHON_EXE"
else
  if command -v python3.11 >/dev/null 2>&1; then
    BASE_PY="python3.11"
  elif command -v python3 >/dev/null 2>&1; then
    BASE_PY="python3"
  else
    echo "ERROR: python3.11 or python3 not found."
    exit 1
  fi

  "$BASE_PY" -m venv .venv311

  if [[ -x "$WIN_PYTHON_EXE" ]]; then
    PYTHON_EXE="$WIN_PYTHON_EXE"
  elif [[ -x "$LINUX_PYTHON_EXE" ]]; then
    PYTHON_EXE="$LINUX_PYTHON_EXE"
  else
    echo "ERROR: Failed to create .venv311 virtual environment."
    exit 1
  fi
fi

"$PYTHON_EXE" -m pip install --upgrade pip
"$PYTHON_EXE" -m pip install -r requirements.txt
"$PYTHON_EXE" cli_app.py
