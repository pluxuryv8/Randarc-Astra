# Randarc Astra

Randarc Astra — локальный desktop-ассистент с UI на `Tauri + React` и API на `FastAPI`. Основной поток: создать run -> определить интент (`CHAT`, `ACT`, `ASK_CLARIFY`) -> либо вернуть текстовый ответ, либо построить/выполнить план шагов через skills -> стримить события в UI через SSE (`apps/api/routes/runs.py:465`, `core/intent_router.py:12`, `core/run_engine.py:24`, `apps/api/routes/run_events.py:15`).

## Что работает по факту

- Чат и интент-роутинг: `POST /api/v1/projects/{project_id}/runs` возвращает `kind=chat|act|clarify` (`apps/api/routes/runs.py:465`).
- Память пользователя: API `GET/POST/DELETE /api/v1/memory/*` + сохранение через skill `memory_save` (`apps/api/routes/memory.py:20`, `core/planner.py:57`).
- Reminders: API `GET/POST/DELETE /api/v1/reminders/*` + scheduler при старте API (`apps/api/routes/reminders.py:31`, `apps/api/main.py:46`, `core/reminders/scheduler.py:197`).
- Web research: плановый `KIND_WEB_RESEARCH` -> skill `web_research` (`core/planner.py:25`, `core/planner.py:52`).
- Autopilot/computer actions через desktop bridge (`core/planner.py:51`, `core/executor/computer_executor.py:163`, `apps/desktop/src-tauri/src/bridge.rs:127`).
- Approval gate для рискованных шагов (`core/planner.py:62`, `core/run_engine.py:34`, `apps/api/routes/runs.py:939`).
- SSE события для UI (`apps/api/routes/run_events.py:15`, `apps/desktop/src/shared/api/eventStream.ts:145`, `apps/desktop/src/shared/store/appStore.ts:85`).

## Быстрый старт

### 1) Требования

- `node` (`scripts/run.sh:27`)
- `cargo` (`scripts/run.sh:32`)
- Python `3.11+` (`scripts/run.sh:38`, `scripts/run.sh:45`)
- `tesseract` для OCR (`scripts/doctor.sh:82`, `core/executor/computer_executor.py:97`)
- Ollama для local LLM (`core/brain/router.py:81`, `scripts/doctor.sh:108`)

### 2) Установка и запуск

```bash
./scripts/astra dev
```

Что делает `./scripts/astra dev`:

- нормализует адреса API/Bridge (`scripts/astra:9`, `scripts/astra:11`),
- запускает `./scripts/run.sh --background` (`scripts/astra:148`),
- поднимает API (`uvicorn`) и desktop (`tauri dev`) (`scripts/run.sh:128`, `scripts/run.sh:142`),
- проверяет порты API/Vite/Bridge (`scripts/astra:157`, `scripts/astra:159`).

Остановка:

```bash
./scripts/astra stop
```

### 3) Проверка, что всё поднялось

```bash
./scripts/astra status
./scripts/doctor.sh prereq
./scripts/doctor.sh runtime
```

`doctor runtime` проверяет порты, `/auth/status`, создание проекта/run и SSE (`scripts/doctor.sh:207`, `scripts/doctor.sh:286`, `scripts/doctor.sh:315`, `scripts/doctor.sh:341`).

## Порты и URL

| Что | По умолчанию | Источник |
|---|---|---|
| API base | `http://127.0.0.1:8055/api/v1` | `scripts/lib/address_config.sh:6` |
| API port | `8055` | `scripts/lib/address_config.sh:4` |
| Bridge base | `http://127.0.0.1:43124` | `scripts/lib/address_config.sh:7` |
| Bridge port | `43124` | `scripts/lib/address_config.sh:5` |
| Vite dev server | `5173` | `scripts/run.sh:78`, `apps/desktop/src-tauri/tauri.conf.json:4` |
| Ollama | `http://127.0.0.1:11434` | `core/brain/router.py:81` |

## Конфигурация (ключевые ENV)

Полная таблица: `docs/CONFIG.md`.

| Переменная | Назначение | Дефолт | Где используется |
|---|---|---|---|
| `ASTRA_API_BASE_URL` | База API (`/api/v1`) | `http://127.0.0.1:8055/api/v1` | `scripts/lib/address_config.sh:59` |
| `ASTRA_API_PORT` | Порт API | `8055` | `scripts/lib/address_config.sh:69` |
| `ASTRA_BRIDGE_BASE_URL` | База desktop bridge | `http://127.0.0.1:43124` | `scripts/lib/address_config.sh:82` |
| `ASTRA_BRIDGE_PORT` | Порт bridge | `43124` | `scripts/lib/address_config.sh:92` |
| `VITE_ASTRA_API_BASE_URL` | API base для desktop UI | берётся из `ASTRA_API_BASE_URL` | `scripts/lib/address_config.sh:155`, `apps/desktop/src/shared/api/config.ts:45` |
| `VITE_ASTRA_BRIDGE_BASE_URL` | Bridge base для desktop UI | берётся из `ASTRA_BRIDGE_BASE_URL` | `scripts/lib/address_config.sh:156`, `apps/desktop/src/shared/api/config.ts:53` |
| `ASTRA_BASE_DIR` | Базовая директория API | repo root | `apps/api/config.py:16` |
| `ASTRA_DATA_DIR` | Директория данных (`.astra`) | `<ASTRA_BASE_DIR>/.astra` | `apps/api/config.py:17` |
| `ASTRA_AUTH_MODE` | `local` или `strict` | `local` | `apps/api/auth.py:20` |
| `ASTRA_LLM_LOCAL_BASE_URL` | URL локальной LLM | `http://127.0.0.1:11434` | `core/brain/router.py:81` |
| `ASTRA_LLM_LOCAL_CHAT_MODEL` | локальная chat модель | `qwen2.5:7b-instruct` | `core/brain/router.py:82` |
| `ASTRA_CLOUD_ENABLED` | разрешить cloud-route | `false` | `core/brain/router.py:76` |
| `ASTRA_AUTO_CLOUD_ENABLED` | автопереход в cloud | `false` | `core/brain/router.py:97` |
| `OPENAI_API_KEY` | ключ cloud провайдера | отсутствует | `core/brain/router.py:75` |
| `ASTRA_REMINDERS_ENABLED` | включить scheduler reminders | `true` | `core/reminders/scheduler.py:135` |
| `ASTRA_TIMEZONE` | TZ для reminders | системная TZ, fallback UTC | `core/reminders/scheduler.py:63` |

## Примеры использования

### Минимальный API smoke (local auth)

```bash
# 1) создать проект
curl -sS -X POST http://127.0.0.1:8055/api/v1/projects \
  -H 'Content-Type: application/json' \
  -d '{"name":"quickstart","tags":[],"settings":{}}'

# 2) создать run
curl -sS -X POST http://127.0.0.1:8055/api/v1/projects/<project_id>/runs \
  -H 'Content-Type: application/json' \
  -d '{"query_text":"Запомни, что я люблю короткие ответы","mode":"plan_only"}'
```

Контракты endpoint'ов: `docs/API.md`.

### Тесты и линт

```bash
python3 -m pytest -q
npm --prefix apps/desktop run test
npm --prefix apps/desktop run lint
```

## Troubleshooting

Коротко:

- `Missing VITE_ASTRA_API_BASE_URL`/`VITE_ASTRA_BRIDGE_BASE_URL` — UI не получил адреса (`apps/desktop/src/shared/api/config.ts:47`, `apps/desktop/src/shared/api/config.ts:55`).
- `Address mismatch ...` — конфликт `ASTRA_*` и `VITE_*` (`scripts/lib/address_config.sh:146`, `scripts/lib/address_config.sh:150`).
- `Ollama not reachable` — проверка в doctor (`scripts/doctor.sh:108`).
- `401 invalid_token` в strict-режиме — см. auth flow (`apps/api/auth.py:104`, `apps/api/auth.py:110`).

Подробно: `docs/TROUBLESHOOTING.md`.

## Структура репозитория

```text
apps/api        FastAPI + маршруты
apps/desktop    Tauri + React desktop UI
core            planner/brain/executor/reminders/safety
memory          SQLite store + migrations
skills          skills и манифесты
scripts         запуск/диагностика/smoke
prompts         системные prompt-шаблоны
```

## Безопасность

- В `ASTRA_AUTH_MODE=local` loopback-клиенты проходят без bearer (`apps/api/auth.py:78`, `apps/api/auth.py:83`).
- В `ASTRA_AUTH_MODE=strict` токен обязателен (`apps/api/auth.py:104`).
- Session token хранится в `ASTRA_DATA_DIR/auth.token` (`apps/api/auth.py:37`, `apps/api/auth.py:52`).
- Desktop bridge слушает локальный HTTP и открывает OS-control endpoint'ы (`apps/desktop/src-tauri/src/bridge.rs:107`, `apps/desktop/src-tauri/src/bridge.rs:127`).
- CORS bridge сейчас `*` (`apps/desktop/src-tauri/src/bridge.rs:145`).

Подробно: `docs/SECURITY.md`.

## Актуальные документы

- `docs/CONFIG.md`
- `docs/API.md`
- `docs/ARCHITECTURE.md`
- `docs/TROUBLESHOOTING.md`
- `docs/SECURITY.md`
- `docs/DEVELOPMENT.md`

Исторические аналитические материалы лежат в `archive/`.
