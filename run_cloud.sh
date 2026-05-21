#!/usr/bin/env bash
set -euo pipefail

# Bash-first launcher for Linux/Cloud and Git Bash.
# Uses Python 3.11 and installs wheels only to avoid local C/C++ builds.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if command -v python3.11 >/dev/null 2>&1; then
  PY_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
else
  echo "ERROR: python3.11 or python3 was not found in PATH."
  exit 1
fi

if [[ ! -d ".venv311" ]]; then
  "$PY_BIN" -m venv .venv311
fi

# shellcheck disable=SC1091
source .venv311/Scripts/activate 2>/dev/null || source .venv311/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install --only-binary=:all: -r requirements.txt

PORT="${PORT:-8501}"
exec python -m streamlit run app.py --server.headless true --server.address 0.0.0.0 --server.port "$PORT"
