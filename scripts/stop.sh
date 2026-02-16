#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/address_config.sh"

if ! apply_resolved_address_env; then
  echo "Некорректная адресная конфигурация (API/Bridge)." >&2
  exit 1
fi

API_PORT="$ASTRA_API_PORT"
BRIDGE_PORT="$ASTRA_BRIDGE_PORT"

if [ -f .astra/api.pid ]; then
  kill "$(cat .astra/api.pid)" >/dev/null 2>&1 || true
  rm -f .astra/api.pid
fi

if [ -f .astra/tauri.pid ]; then
  kill "$(cat .astra/tauri.pid)" >/dev/null 2>&1 || true
  rm -f .astra/tauri.pid
fi

pids=$(lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN -t 2>/dev/null || true)
if [ -n "$pids" ]; then
  kill $pids >/dev/null 2>&1 || true
  echo "Остановлен API на порту $API_PORT"
fi

pids=$(lsof -nP -iTCP:5173 -sTCP:LISTEN -t 2>/dev/null || true)
if [ -n "$pids" ]; then
  kill $pids >/dev/null 2>&1 || true
  echo "Остановлен Vite (порт 5173)"
fi

pids=$(lsof -nP -iTCP:"$BRIDGE_PORT" -sTCP:LISTEN -t 2>/dev/null || true)
if [ -n "$pids" ]; then
  kill $pids >/dev/null 2>&1 || true
  echo "Остановлен Bridge (порт $BRIDGE_PORT)"
fi

pids=$(pgrep -f "tauri dev" || true)
if [ -n "$pids" ]; then
  kill $pids >/dev/null 2>&1 || true
  echo "Остановлен Tauri dev"
fi
