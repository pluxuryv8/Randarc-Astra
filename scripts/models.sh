#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ASTRA_DATA_DIR:-$ROOT_DIR/.astra}"
MODELS_DIR="$DATA_DIR/models"
CHAT_MODEL="${ASTRA_LLM_LOCAL_CHAT_MODEL:-qwen2.5:7b-instruct}"
CHAT_FAST_MODEL="${ASTRA_LLM_LOCAL_CHAT_MODEL_FAST:-qwen2.5:3b-instruct}"
CHAT_COMPLEX_MODEL="${ASTRA_LLM_LOCAL_CHAT_MODEL_COMPLEX:-$CHAT_MODEL}"
CODE_MODEL="${ASTRA_LLM_LOCAL_CODE_MODEL:-deepseek-coder-v2:16b-lite-instruct-q8_0}"
LEGACY_SAIGA_GGUF_PATH="$MODELS_DIR/saiga_nemo_12b.gguf"

ok() { echo "OK  $*"; }
warn() { echo "WARN $*"; }
fail() { echo "FAIL $*"; exit 1; }

ensure_ollama() {
  if ! command -v ollama >/dev/null 2>&1; then
    fail "ollama not found. Install Ollama and retry."
  fi
  if ! ollama list >/dev/null 2>&1; then
    fail "ollama is not reachable. Start ollama and retry (ollama serve)."
  fi
  ok "ollama is available"
}

normalize_name() {
  local model="$1"
  if [[ "$model" == *:* ]]; then
    echo "$model"
  else
    echo "${model}:latest"
  fi
}

pull_model() {
  local model="$1"
  if [ -z "$model" ]; then
    return 0
  fi
  ok "Pulling Ollama model: $model"
  ollama pull "$model"
}

install_chat_models() {
  local models=("$CHAT_MODEL" "$CHAT_FAST_MODEL" "$CHAT_COMPLEX_MODEL")
  local model
  declare -A seen=()
  for model in "${models[@]}"; do
    [ -z "$model" ] && continue
    if [[ -n "${seen[$model]:-}" ]]; then
      continue
    fi
    seen["$model"]=1
    pull_model "$model"
  done
}

install_deepseek() {
  pull_model "$CODE_MODEL"
}

verify_models() {
  local list
  list="$(ollama list | awk 'NR>1 {print $1}')"
  local missing=0
  local models=("$CHAT_MODEL" "$CHAT_FAST_MODEL" "$CHAT_COMPLEX_MODEL" "$CODE_MODEL")
  local model
  declare -A seen=()
  for model in "${models[@]}"; do
    [ -z "$model" ] && continue
    if [[ -n "${seen[$model]:-}" ]]; then
      continue
    fi
    seen["$model"]=1
    local normalized
    normalized="$(normalize_name "$model")"
    if ! printf "%s\n" "$list" | grep -Fxq "$model" && ! printf "%s\n" "$list" | grep -Fxq "$normalized"; then
      warn "Missing model: $model"
      missing=1
    fi
  done
  if [ "$missing" -eq 0 ]; then
    ok "Models present: chat=$CHAT_MODEL fast=$CHAT_FAST_MODEL complex=$CHAT_COMPLEX_MODEL code=$CODE_MODEL"
    return 0
  fi
  return 1
}

cmd_install() {
  ensure_ollama
  install_chat_models
  install_deepseek
  ok "Ollama models installed"
  ollama list
  if ! verify_models; then
    fail "Model verification failed"
  fi
}

cmd_verify() {
  ensure_ollama
  if verify_models; then
    ok "PASS"
    return 0
  fi
  fail "FAIL: one or more models are missing"
}

cmd_clean() {
  if [ "${CONFIRM:-}" != "1" ]; then
    echo "This will remove legacy downloaded files from: $MODELS_DIR"
    echo "Run: CONFIRM=1 $0 clean"
    exit 1
  fi
  if [ -f "$LEGACY_SAIGA_GGUF_PATH" ]; then
    rm -f "$LEGACY_SAIGA_GGUF_PATH"
    ok "Removed legacy file: $LEGACY_SAIGA_GGUF_PATH"
  else
    warn "No legacy GGUF file found at: $LEGACY_SAIGA_GGUF_PATH"
  fi
}

case "${1:-}" in
  install)
    cmd_install
    ;;
  verify)
    cmd_verify
    ;;
  clean)
    cmd_clean
    ;;
  *)
    echo "Usage: $0 {install|verify|clean}"
    echo "Env: ASTRA_DATA_DIR, ASTRA_LLM_LOCAL_CHAT_MODEL, ASTRA_LLM_LOCAL_CHAT_MODEL_FAST, ASTRA_LLM_LOCAL_CHAT_MODEL_COMPLEX, ASTRA_LLM_LOCAL_CODE_MODEL"
    exit 1
    ;;
 esac
