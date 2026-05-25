#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_EXE="$SCRIPT_DIR/.venv311/Scripts/python.exe"

if [[ ! -x "$PYTHON_EXE" ]]; then
  echo ".venv311 not found. Create it first with Python 3.11:"
  echo "  py -3.11 -m venv .venv311"
  echo "Then rerun: bash ./run_cli.sh"
  exit 1
fi

"$PYTHON_EXE" -m pip install -r requirements.txt
"$PYTHON_EXE" cli_app.py
