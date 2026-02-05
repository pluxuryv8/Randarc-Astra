#!/usr/bin/env bash
set -euo pipefail

API_PORT="${ASTRA_API_PORT:-8055}"

pids=$(lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN -t 2>/dev/null || true)
if [ -n "$pids" ]; then
  kill $pids >/dev/null 2>&1 || true
  echo "Остановлен API на порту $API_PORT"
else
  echo "API на порту $API_PORT не найден"
fi

pids=$(lsof -nP -iTCP:5173 -sTCP:LISTEN -t 2>/dev/null || true)
if [ -n "$pids" ]; then
  kill $pids >/dev/null 2>&1 || true
  echo "Остановлен Vite (порт 5173)"
fi
