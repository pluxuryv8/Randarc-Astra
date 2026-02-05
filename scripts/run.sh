#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v node >/dev/null 2>&1; then
  echo "Нужен Node.js (node). Установи Node и повтори запуск." >&2
  exit 1
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "Нужен Rust (cargo). Установи rustup и повтори запуск." >&2
  exit 1
fi

PYTHON_BIN=""
if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "Нужен Python 3.11+ (рекомендуется 3.11)." >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip >/dev/null
python -m pip install -r apps/api/requirements.txt >/dev/null

npm --prefix apps/desktop install >/dev/null

API_PORT="${ASTRA_API_PORT:-8055}"
export ASTRA_API_PORT="$API_PORT"

cleanup() {
  if [ -n "${API_PID:-}" ] && kill -0 "$API_PID" >/dev/null 2>&1; then
    kill "$API_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

python -m uvicorn apps.api.main:app --host 127.0.0.1 --port "$API_PORT" >/dev/null 2>&1 &
API_PID=$!

source "$HOME/.cargo/env" >/dev/null 2>&1 || true

npm --prefix apps/desktop run tauri dev
