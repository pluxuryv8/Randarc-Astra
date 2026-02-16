# Architecture (Current State)

## Components

- Desktop UI: `apps/desktop` (`Tauri + React`) (`apps/desktop/package.json:1`, `apps/desktop/src-tauri/tauri.conf.json:1`).
- API: `apps/api` (`FastAPI`) (`apps/api/main.py:24`).
- Core orchestration: planner/engine/skills in `core/` (`core/planner.py:22`, `core/run_engine.py:16`).
- Persistent state: SQLite store + migrations in `memory/` (`memory/store.py:20`, `memory/db.py:63`).
- Executable skills: `skills/*` + manifests (`core/skills/registry.py:31`, `skills/registry/registry.json:1`).

## Main Runtime Flow

1. Desktop sends request to API: `POST /api/v1/projects/{project_id}/runs` (`apps/api/routes/runs.py:465`).
2. API decides intent (`CHAT`, `ACT`, `ASK_CLARIFY`) via `IntentRouter` + semantic layer (`apps/api/routes/runs.py:492`, `core/intent_router.py:87`).
3. `CHAT`: return `chat_response` (with fallback on LLM failures) (`apps/api/routes/runs.py:662`, `apps/api/routes/runs.py:733`).
4. `ACT`: create plan and run skills (`apps/api/routes/runs.py:652`, `core/run_engine.py:24`, `core/run_engine.py:164`).
5. Events are persisted and streamed to UI through SSE (`memory/store.py:1421`, `apps/api/routes/run_events.py:15`, `apps/desktop/src/shared/api/eventStream.ts:145`).

## Planning and Skills

Plan kinds and mapping to skills are hardcoded in planner:

- `WEB_RESEARCH` -> `web_research`
- `MEMORY_COMMIT` -> `memory_save`
- `REMINDER_CREATE` -> `reminder_create`
- `BROWSER_RESEARCH_UI`/`COMPUTER_ACTIONS`/`DOCUMENT_WRITE`/`FILE_ORGANIZE`/`CODE_ASSIST` -> `autopilot_computer`

Source: `core/planner.py:22`, `core/planner.py:48`.

Run execution lifecycle: `created -> running -> done/failed/canceled/paused` (`core/run_engine.py:56`, `core/run_engine.py:63`, `core/run_engine.py:79`, `core/run_engine.py:82`).

## API Surface (high level)

Mounted routers: projects, runs, run_events, skills, artifacts, secrets, memory, reminders, auth (`apps/api/main.py:48`, `apps/api/main.py:56`).

Key endpoints:

- projects: `apps/api/routes/projects.py:9`
- runs + approvals: `apps/api/routes/runs.py:465`, `apps/api/routes/runs.py:939`
- SSE: `apps/api/routes/run_events.py:15`
- memory: `apps/api/routes/memory.py:11`
- reminders: `apps/api/routes/reminders.py:12`
- skills list/reload: `apps/api/routes/skills.py:7`
- auth status/bootstrap: `apps/api/routes/auth.py:10`

## Desktop Bridge

Bridge is a local HTTP server started by Tauri with endpoints:

- `/computer/preview`, `/computer/execute`
- `/shell/preview`, `/shell/execute`
- `/autopilot/capture`, `/autopilot/act`, `/autopilot/permissions`

Source: `apps/desktop/src-tauri/src/bridge.rs:111`, `apps/desktop/src-tauri/src/bridge.rs:127`.

Default bind is loopback on port `43124` unless overridden by env (`apps/desktop/src-tauri/src/bridge.rs:104`, `apps/desktop/src-tauri/src/bridge.rs:107`).

## Data and Storage

- `ASTRA_BASE_DIR` / `ASTRA_DATA_DIR` define storage root (`apps/api/config.py:16`, `apps/api/config.py:17`).
- DB file is `astra.db` in data dir (`memory/db.py:7`).
- Migrations apply at startup (`memory/db.py:63`, `memory/db.py:66`).

## Auth and Transport Modes

- Auth modes: `local`, `strict` (`apps/api/auth.py:17`).
- `local`: loopback exempt from bearer token (`apps/api/auth.py:78`, `apps/api/auth.py:83`).
- `strict`: token required (`apps/api/auth.py:104`).
- LLM route local/cloud with env policy flags (`core/brain/router.py:76`, `core/brain/router.py:97`, `core/brain/router.py:194`).
