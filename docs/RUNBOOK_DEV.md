# RUNBOOK_DEV (фактический запуск)

## Быстрый старт
```bash
./scripts/run.sh
./scripts/doctor.sh prereq
./scripts/doctor.sh runtime
```
(см. `scripts/run.sh:1-134`, `scripts/doctor.sh:1-200`)

Остановка:
```bash
./scripts/stop.sh
```
(см. `scripts/stop.sh:1-31`)

## Как поднять API
- Команда (dev):
```bash
source .venv/bin/activate
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8055
```
(см. `apps/api/main.py:1-39`, `scripts/run.sh:83-83`)

- Health/ключевые эндпоинты:
  - `GET /api/v1/auth/status` (см. `apps/api/routes/auth.py:9-13`).
  - `GET /api/v1/skills` (см. `apps/api/routes/skills.py:7-18`).
  - `GET /api/v1/projects` (auth) (см. `apps/api/routes/projects.py:10-28`).

## Как поднять Desktop
```bash
npm --prefix apps/desktop run tauri dev
```
(см. `apps/desktop/package.json:6-14`)

UI читает API base из `VITE_API_BASE` или `VITE_API_PORT` (по умолчанию 8055) (см. `apps/desktop/src/api.ts:14-16`).

## OCR prerequisites
- Установить Tesseract:
```bash
brew install tesseract
```
- Установить Python deps в API окружение (`.venv` создаёт `./scripts/run.sh`):
```bash
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r apps/api/requirements.txt
```

## Как прогнать doctor
```bash
./scripts/doctor.sh prereq
./scripts/doctor.sh runtime
```
- `prereq` проверяет зависимости/ключи/ollama без требования запущенных сервисов.
- `runtime` проверяет поднятые сервисы и health-запросы API.
- Использует `ASTRA_API_PORT`/`ASTRA_API_BASE` при наличии (см. `scripts/doctor.sh:9-13`).

## Проверки качества (одна команда)
```bash
./scripts/check.sh
```
(см. `scripts/check.sh:1-15`)

## Типовые ошибки и как лечить (фактически встретились)
- `pytest` падал из-за отсутствия `httpx` для `starlette.testclient`.
  - Фикс: добавить `httpx` в `requirements-dev.txt` (см. `requirements-dev.txt:1-3`).
- `ruff check .` возвращает множество нарушений (import order, line length и т.п.).
  - Это уже существующее состояние; исправление не выполнялось в рамках baseline (см. вывод `ruff check .`).
