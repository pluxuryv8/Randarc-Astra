# Troubleshooting

## 1) UI error: `Missing VITE_ASTRA_API_BASE_URL` or `Missing VITE_ASTRA_BRIDGE_BASE_URL`

Причина: frontend ожидает явные `VITE_ASTRA_*` адреса или runtime config (`apps/desktop/src/shared/api/config.ts:45`, `apps/desktop/src/shared/api/config.ts:53`).

Проверка и исправление:

```bash
./scripts/doctor.sh prereq
python scripts/diag_addresses.py
```

Скрипт запуска обычно сам синхронизирует адреса (`scripts/lib/address_config.sh:155`, `scripts/lib/address_config.sh:156`).

## 2) `Address mismatch` при старте

Причина: конфликт между `ASTRA_*` и `VITE_*` переменными.

Источник проверки: `scripts/lib/address_config.sh:146`, `scripts/lib/address_config.sh:150`.

Исправление:

- оставить только `ASTRA_API_BASE_URL` и `ASTRA_BRIDGE_BASE_URL` в `.env`;
- убрать вручную заданные конфликтующие `VITE_ASTRA_*`;
- перезапустить `./scripts/astra dev`.

## 3) `doctor prereq`: `Ollama not reachable`

Проверка делается по `GET /api/tags` (`scripts/doctor.sh:108`, `scripts/doctor.sh:113`).

Команды:

```bash
curl -sS http://127.0.0.1:11434/api/tags
./scripts/models.sh verify
./scripts/models.sh install
```

## 4) `401` / `invalid_token`

Поведение auth:

- `local`: loopback без bearer допускается (`apps/api/auth.py:78`, `apps/api/auth.py:83`);
- `strict`: токен обязателен (`apps/api/auth.py:104`).

Проверка:

```bash
curl -i http://127.0.0.1:8055/api/v1/auth/status
```

Bootstrap токена:

```bash
curl -X POST http://127.0.0.1:8055/api/v1/auth/bootstrap \
  -H 'Content-Type: application/json' \
  -d '{"token":"<your_token>"}'
```

## 5) `doctor runtime` иногда падает на `POST /projects/{id}/runs`, но API жив

В `scripts/doctor.sh` JSON из shell подставляется в Python через тройные кавычки (`scripts/doctor.sh:343`).
Если в ответе есть экранированные кавычки, парсинг может дать ложный `FAIL`.

Проверка вручную:

```bash
# создать проект
curl -sS -X POST http://127.0.0.1:8055/api/v1/projects \
  -H 'Content-Type: application/json' \
  -d '{"name":"doctor-debug","tags":["doctor"],"settings":{}}'

# создать run
curl -sS -X POST http://127.0.0.1:8055/api/v1/projects/<project_id>/runs \
  -H 'Content-Type: application/json' \
  -d '{"query_text":"doctor smoke","mode":"plan_only"}'
```

Если второй запрос возвращает `200` и `run.id`, это ложный провал doctor-шага.

## 6) Reminders не доставляются в Telegram

Факты:

- default delivery -> `telegram`, только когда заданы `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` (`apps/api/routes/reminders.py:16`, `apps/api/routes/reminders.py:18`);
- иначе fallback `local` (`apps/api/routes/reminders.py:20`);
- scheduler можно выключить `ASTRA_REMINDERS_ENABLED=false` (`core/reminders/scheduler.py:135`).

Проверки:

```bash
printenv TELEGRAM_BOT_TOKEN
printenv TELEGRAM_CHAT_ID
curl -sS http://127.0.0.1:8055/api/v1/reminders
```

## 7) Bridge `503 НЕДОСТУПНО` на `/computer/*` или `/autopilot/*`

Bridge отвечает `503`, если desktop функциональность не инициализирована (`apps/desktop/src-tauri/src/bridge.rs:200`, `apps/desktop/src-tauri/src/bridge.rs:227`).

Проверки:

```bash
./scripts/astra status
curl -sS http://127.0.0.1:43124/autopilot/permissions
```

Убедитесь, что desktop запущен через `npm --prefix apps/desktop run tauri dev` (или `./scripts/astra dev`).

## 8) Быстрый набор команд диагностики

```bash
./scripts/astra status
./scripts/doctor.sh prereq
./scripts/doctor.sh runtime
python scripts/diag_addresses.py
./scripts/astra logs api
./scripts/astra logs desktop
```
