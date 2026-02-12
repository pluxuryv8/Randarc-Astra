#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:-dry-run}"
if [[ "$MODE" != "dry-run" && "$MODE" != "safe-run" ]]; then
  echo "Usage: $0 [dry-run|safe-run]" >&2
  exit 1
fi

PYTHON_BIN=""
if [ -x ".venv/bin/python3" ]; then
  PYTHON_BIN=".venv/bin/python3"
elif [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "FAIL: python not found" >&2
  exit 1
fi

echo "== Doctor (prereq) =="
./scripts/doctor.sh prereq

echo "== Pytest =="
"$PYTHON_BIN" -m pytest -q

echo "== QA Scenarios (${MODE}) =="
"$PYTHON_BIN" scripts/run_scenarios.py --mode "$MODE"
