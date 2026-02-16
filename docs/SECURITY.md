# Security Notes (Current State)

Документ описывает фактическое поведение текущего кода без предположений.

## Auth model

- Режимы auth: `local` и `strict` (`apps/api/auth.py:17`).
- В `local` loopback-клиенты проходят без bearer (`apps/api/auth.py:78`, `apps/api/auth.py:83`).
- В `strict` bearer/query token обязателен (`apps/api/auth.py:104`, `apps/api/auth.py:110`).
- Session token хранится в файле `ASTRA_DATA_DIR/auth.token` (`apps/api/auth.py:37`, `apps/api/auth.py:52`).
- В БД хранится hash+salt токена (`apps/api/auth.py:29`, `apps/api/auth.py:64`).

Практический вывод: для предсказуемого доступа и CI используйте `ASTRA_AUTH_MODE=strict`.

## Network surface

- API обычно поднимается на loopback `127.0.0.1` (`scripts/run.sh:128`).
- Desktop bridge слушает локальный HTTP (`apps/desktop/src-tauri/src/bridge.rs:107`).
- Bridge открывает OS-control endpoint'ы (`apps/desktop/src-tauri/src/bridge.rs:127`).
- CORS bridge установлен в `*` (`apps/desktop/src-tauri/src/bridge.rs:145`).

Практический вывод: проект рассчитан на доверенный локальный контур.

## Secrets handling

Порядок получения секрета:

1. runtime secrets,
2. env,
3. local JSON,
4. encrypted vault.

Source: `core/secrets.py:71`, `core/secrets.py:75`, `core/secrets.py:77`, `core/secrets.py:81`.

Пути/переменные:

- `ASTRA_LOCAL_SECRETS_PATH` (default `config/local.secrets.json`) (`core/secrets.py:14`),
- `ASTRA_VAULT_PATH` (default `.astra/vault.bin`) (`core/secrets.py:11`),
- `ASTRA_VAULT_PASSPHRASE` (`core/secrets.py:18`).

## Approval gate

- Danger flags назначаются planner'ом (`core/planner.py:62`, `core/planner.py:1224`).
- Шаги с danger флагами требуют approval (`core/planner.py:385`, `core/planner.py:1228`).
- Исполнение проверяет approval до действий (`core/run_engine.py:34`, `core/skills/runner.py:39`, `core/executor/computer_executor.py:715`).

## Cloud routing

- Cloud выключается, если нет `OPENAI_API_KEY`, даже при `ASTRA_CLOUD_ENABLED=true` (`core/brain/router.py:75`, `core/brain/router.py:77`).
- Для cloud-route выполняется санитизация контекста (`core/brain/router.py:235`, `core/llm_routing.py:183`).

## Minimal hardening checklist

1. Включить `ASTRA_AUTH_MODE=strict`.
2. Ограничить окружение выполнения локальной машиной.
3. Не хранить `ASTRA_VAULT_PASSPHRASE` в открытом shell history.
4. Проверять `./scripts/doctor.sh prereq` перед запуском.
