# Configuration Reference

Документ фиксирует фактические переменные окружения и дефолты из текущего кода.
Если переменная не найдена в коде — здесь не перечисляется.

## Addressing and Startup

| Variable | Purpose | Default | Used in |
|---|---|---|---|
| `ASTRA_API_BASE_URL` | Base URL API (must include `/api/v1`) | `http://127.0.0.1:8055/api/v1` | `scripts/lib/address_config.sh:59`, `scripts/lib/address_config.sh:121` |
| `ASTRA_API_BASE` | Alias for API base | mirrors `ASTRA_API_BASE_URL` | `scripts/lib/address_config.sh:59`, `scripts/lib/address_config.sh:139` |
| `ASTRA_API_PORT` | API port | `8055` | `scripts/lib/address_config.sh:4`, `scripts/lib/address_config.sh:69` |
| `ASTRA_BRIDGE_BASE_URL` | Desktop bridge base URL | `http://127.0.0.1:43124` | `scripts/lib/address_config.sh:82`, `scripts/lib/address_config.sh:122` |
| `ASTRA_BRIDGE_PORT` | Desktop bridge port | `43124` | `scripts/lib/address_config.sh:5`, `scripts/lib/address_config.sh:92` |
| `ASTRA_DESKTOP_BRIDGE_PORT` | Legacy alias for bridge port | `43124` | `scripts/lib/address_config.sh:84`, `scripts/lib/address_config.sh:96`, `scripts/lib/address_config.sh:144` |
| `VITE_ASTRA_API_BASE_URL` | API base for desktop frontend | synced from `ASTRA_API_BASE_URL` by startup scripts | `scripts/lib/address_config.sh:155`, `apps/desktop/src/shared/api/config.ts:45` |
| `VITE_ASTRA_BRIDGE_BASE_URL` | Bridge base for desktop frontend | synced from `ASTRA_BRIDGE_BASE_URL` by startup scripts | `scripts/lib/address_config.sh:156`, `apps/desktop/src/shared/api/config.ts:53` |
| `VITE_ASTRA_BASE_DIR` | Base dir exposed to desktop runtime | set by startup script | `scripts/run.sh:83`, `apps/desktop/src/shared/api/config.ts:72` |
| `VITE_ASTRA_DATA_DIR` | Data dir exposed to desktop runtime | set by startup script | `scripts/run.sh:84`, `apps/desktop/src/shared/api/config.ts:71` |
| `ASTRA_BASE_DIR` | API base directory | repo root | `apps/api/config.py:16` |
| `ASTRA_DATA_DIR` | Data directory | `<ASTRA_BASE_DIR>/.astra` | `apps/api/config.py:17`, `scripts/run.sh:80` |
| `ASTRA_LOG_DIR` | API/Tauri logs directory | `.astra/logs` | `scripts/run.sh:86` |

## Auth

| Variable | Purpose | Default | Used in |
|---|---|---|---|
| `ASTRA_AUTH_MODE` | API auth mode (`local` or `strict`) | `local` | `apps/api/auth.py:20`, `scripts/run.sh:23` |
| `ASTRA_SESSION_TOKEN` | Token override for scripts/doctor/smoke | none | `scripts/doctor.sh:261`, `scripts/smoke_approvals_sse.sh:26` |

Auth behavior:

- `local`: loopback host can call API without bearer token (`apps/api/auth.py:78`, `apps/api/auth.py:83`).
- `strict`: bearer/query token required (`apps/api/auth.py:104`, `apps/api/auth.py:110`).

## LLM Routing

| Variable | Purpose | Default | Used in |
|---|---|---|---|
| `ASTRA_LLM_LOCAL_BASE_URL` | Local LLM endpoint | `http://127.0.0.1:11434` | `core/brain/router.py:81` |
| `ASTRA_LLM_LOCAL_CHAT_MODEL` | Local chat model | `qwen2.5:7b-instruct` | `core/brain/router.py:82` |
| `ASTRA_LLM_LOCAL_CHAT_MODEL_FAST` | Fast local chat model | `qwen2.5:3b-instruct` | `core/brain/router.py:83` |
| `ASTRA_LLM_LOCAL_CHAT_MODEL_COMPLEX` | Complex local chat model | falls back to `ASTRA_LLM_LOCAL_CHAT_MODEL` | `core/brain/router.py:84` |
| `ASTRA_LLM_LOCAL_CODE_MODEL` | Local code model | `deepseek-coder-v2:16b-lite-instruct-q8_0` | `core/brain/router.py:88` |
| `ASTRA_LLM_LOCAL_TIMEOUT_S` | Local model timeout (seconds) | `30` | `core/brain/router.py:89` |
| `ASTRA_LLM_FAST_QUERY_MAX_CHARS` | Fast-model char threshold | `120` | `core/brain/router.py:90` |
| `ASTRA_LLM_FAST_QUERY_MAX_WORDS` | Fast-model words threshold | `18` | `core/brain/router.py:91` |
| `ASTRA_LLM_COMPLEX_QUERY_MIN_CHARS` | Complex-model char threshold | `260` | `core/brain/router.py:92` |
| `ASTRA_LLM_COMPLEX_QUERY_MIN_WORDS` | Complex-model words threshold | `45` | `core/brain/router.py:93` |
| `ASTRA_LLM_CLOUD_BASE_URL` | Cloud LLM base URL | `https://api.openai.com/v1` | `core/brain/router.py:94` |
| `ASTRA_LLM_CLOUD_MODEL` | Cloud model | `gpt-4.1` | `core/brain/router.py:95` |
| `ASTRA_CLOUD_ENABLED` | Enable cloud route | `false` | `core/brain/router.py:76`, `core/brain/router.py:194` |
| `ASTRA_AUTO_CLOUD_ENABLED` | Auto-switch local -> cloud | `false` | `core/brain/router.py:97`, `core/brain/router.py:196` |
| `OPENAI_API_KEY` | Cloud API key | none | `core/brain/router.py:75`, `core/brain/router.py:457` |
| `ASTRA_LLM_MAX_CONCURRENCY` | LLM parallelism | `1` | `core/brain/router.py:98` |
| `ASTRA_LLM_MAX_RETRIES` | Cloud retries | `3` | `core/brain/router.py:99` |
| `ASTRA_LLM_BACKOFF_BASE_MS` | Retry backoff base | `350` | `core/brain/router.py:100` |
| `ASTRA_LLM_BUDGET_PER_RUN` | Budget per run | none | `core/brain/router.py:101` |
| `ASTRA_LLM_BUDGET_PER_STEP` | Budget per step | none | `core/brain/router.py:102` |
| `ASTRA_OWNER_DIRECT_MODE` | Chat system prompt mode | `true` | `apps/api/routes/runs.py:112` |
| `ASTRA_CHAT_FAST_PATH_ENABLED` | Skip semantic pass for short safe chat | `true` | `apps/api/routes/runs.py:116` |
| `ASTRA_CHAT_FAST_PATH_MAX_CHARS` | Fast-chat max chars | `220` | `apps/api/routes/runs.py:120` |
| `ASTRA_QA_MODE` | QA deterministic mode | `false` | `apps/api/routes/runs.py:154`, `core/planner.py:91` |
| `ASTRA_LEGACY_DETECTORS` | Enable legacy planner detectors | `false` | `core/planner.py:97` |

## Executor and OCR

| Variable | Purpose | Default | Used in |
|---|---|---|---|
| `ASTRA_EXECUTOR_MAX_MICRO_STEPS` | Max micro actions per step | `30` | `core/executor/computer_executor.py:87` |
| `ASTRA_EXECUTOR_MAX_NO_PROGRESS` | Max no-progress cycles | `5` | `core/executor/computer_executor.py:88` |
| `ASTRA_EXECUTOR_MAX_TOTAL_TIME_S` | Per-step timeout (seconds) | `600` | `core/executor/computer_executor.py:89` |
| `ASTRA_EXECUTOR_WAIT_AFTER_ACT_MS` | Delay after action | `350` | `core/executor/computer_executor.py:90` |
| `ASTRA_EXECUTOR_WAIT_POLL_MS` | Poll interval while waiting | `500` | `core/executor/computer_executor.py:91` |
| `ASTRA_EXECUTOR_WAIT_TIMEOUT_MS` | Wait timeout | `4000` | `core/executor/computer_executor.py:92` |
| `ASTRA_EXECUTOR_MAX_ACTION_RETRIES` | Retry count for proposed action | `1` | `core/executor/computer_executor.py:93` |
| `ASTRA_EXECUTOR_SCREENSHOT_WIDTH` | Screenshot width | `1280` | `core/executor/computer_executor.py:94` |
| `ASTRA_EXECUTOR_SCREENSHOT_QUALITY` | JPEG quality | `60` | `core/executor/computer_executor.py:95` |
| `ASTRA_EXECUTOR_DRY_RUN` | Dry-run mode | `false` | `core/executor/computer_executor.py:96` |
| `ASTRA_OCR_ENABLED` | OCR usage in executor | `true` | `core/executor/computer_executor.py:97` |
| `ASTRA_OCR_LANG` | OCR languages | `eng+rus` | `core/executor/computer_executor.py:98` |

## Memory, Reminders, Secrets

| Variable | Purpose | Default | Used in |
|---|---|---|---|
| `ASTRA_MEMORY_MAX_CHARS` | Max length of memory content | `4000` | `memory/store.py:60` |
| `ASTRA_REMINDERS_ENABLED` | Enable reminders scheduler | `true` | `core/reminders/scheduler.py:135` |
| `ASTRA_TIMEZONE` | Reminder timezone | system timezone, fallback UTC | `core/reminders/scheduler.py:63`, `core/reminders/scheduler.py:68` |
| `TELEGRAM_BOT_TOKEN` | Telegram delivery token | none | `apps/api/routes/reminders.py:16`, `core/reminders/scheduler.py:29` |
| `TELEGRAM_CHAT_ID` | Telegram delivery chat id | none | `apps/api/routes/reminders.py:17`, `core/reminders/scheduler.py:30` |
| `ASTRA_VAULT_PATH` | Encrypted vault file path | `.astra/vault.bin` | `core/secrets.py:11` |
| `ASTRA_VAULT_PASSPHRASE` | Vault passphrase | none | `core/secrets.py:18` |
| `ASTRA_LOCAL_SECRETS_PATH` | Local plaintext secrets JSON | `config/local.secrets.json` | `core/secrets.py:14` |

## Diagnostics Commands

```bash
./scripts/doctor.sh prereq
./scripts/doctor.sh runtime
python scripts/diag_addresses.py
```

Sources: `scripts/doctor.sh:55`, `scripts/doctor.sh:204`, `scripts/diag_addresses.py:1`.
