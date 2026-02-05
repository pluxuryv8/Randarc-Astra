Ниже — полный разбор в нужном формате. Сначала деревья + entrypoints + зависимости, затем инвентаризация по шаблону.

**Trees + Entrypoints + Dependencies**

**DeepAnalyze**
Tree:
```text
DeepAnalyze/
├── .git/
│   ├── hooks/
│   ├── info/
│   ├── logs/
│   ├── objects/
│   ├── refs/
│   ├── config
│   ├── description
│   ├── HEAD
│   ├── index
│   └── packed-refs
├── API/
│   ├── example/
│   ├── __init__.py
│   ├── admin_api.py
│   ├── chat_api.py
│   ├── config.py
│   ├── file_api.py
│   ├── main.py
│   ├── models.py
│   ├── models_api.py
│   ├── README.md
│   ├── README_ZH.md
│   ├── start_server.py
│   ├── storage.py
│   └── utils.py
├── assets/
├── deepanalyze/
│   ├── ms-swift/
│   ├── SkyRL/
│   ├── add_vocab.py
│   └── README.md
├── demo/
│   ├── chat/
│   ├── cli/
│   ├── deepanalyze_general/
│   ├── jupyter/
│   └── mock_vllm/
├── docker/
├── docs/
├── example/
├── playground/
├── scripts/
├── .gitignore
├── CONTRIBUTION.md
├── deepanalyze.py
├── LICENSE
├── quantize.py
├── README.md
├── requirements.txt
└── run.py
```

Entrypoints:
1. `DeepAnalyze/API/start_server.py` — запуск FastAPI API (вызывает `DeepAnalyze/API/main.py`).
2. `DeepAnalyze/API/main.py` — создание приложения FastAPI и маршрутов.
3. `DeepAnalyze/demo/chat/backend.py` — demo‑backend FastAPI (UI + workspace endpoints).
4. `DeepAnalyze/demo/chat/start.sh` и `DeepAnalyze/demo/chat/start.bat` — запуск demo UI.
5. `DeepAnalyze/demo/cli/api_cli.py` и `DeepAnalyze/demo/cli/api_cli_ZH.py` — CLI интерфейс.
6. `DeepAnalyze/demo/jupyter/CLI.py` и `DeepAnalyze/demo/jupyter/server.py` — Jupyter UI.
7. `DeepAnalyze/run.py` — пример запуска через класс `DeepAnalyzeVLLM`.
8. `DeepAnalyze/deepanalyze.py` — клиент/обертка для vLLM.
9. `DeepAnalyze/quantize.py` — квантизация модели.
10. `DeepAnalyze/docker/Dockerfile` и `DeepAnalyze/docker/docker-compose.yml` — контейнерный запуск.

Dependencies:
1. Python runtime: `DeepAnalyze/requirements.txt` (vllm, numpy, pandas, scikit-learn, seaborn, torch, transformers, matplotlib, requests, websockets, python-multipart, uvicorn, fastapi, openai, pypandoc).
2. Web UI: `DeepAnalyze/demo/chat/frontend/package.json` (Next.js + React).
3. Jupyter UI: `DeepAnalyze/demo/jupyter/pyproject.toml` (jupyterlab, jupyter-mcp-server, fastmcp, openai и др.).
4. Дополнительные наборы зависимостей для обучения: `DeepAnalyze/deepanalyze/ms-swift/requirements/` и `DeepAnalyze/deepanalyze/SkyRL/pyproject.toml`.

---

**ValueCell**
Tree:
```text
valuecell/
├── .git/
├── .github/
├── .vscode/
├── assets/
├── docker/
├── docs/
├── frontend/
│   ├── public/
│   ├── scripts/
│   ├── src/
│   ├── src-tauri/
│   ├── .env.example
│   ├── package.json
│   └── vite.config.ts
├── python/
│   ├── configs/
│   ├── scripts/
│   ├── valuecell/
│   ├── pyproject.toml
│   └── README.md
├── .env.example
├── AGENTS.md
├── LICENSE
├── Makefile
├── README.md
├── SECURITY.md
├── start.ps1
└── start.sh
```

Entrypoints:
1. `valuecell/start.sh` и `valuecell/start.ps1` — запуск frontend+backend и подготовка окружения.
2. `valuecell/python/valuecell/server/main.py` — FastAPI backend (uvicorn).
3. `valuecell/python/valuecell/server/db/init_db.py` — инициализация БД.
4. Агент‑процессы: `valuecell/python/valuecell/agents/*/__main__.py` (например `valuecell/python/valuecell/agents/research_agent/__main__.py`).
5. Frontend: `valuecell/frontend/src/root.tsx`, маршрутизация в `valuecell/frontend/src/routes.ts`.
6. Tauri desktop: `valuecell/frontend/src-tauri/src/main.rs`.

Dependencies:
1. Backend: `valuecell/python/pyproject.toml` (fastapi, uvicorn, a2a-sdk, agno, yfinance, akshare, ccxt, sqlalchemy, aiosqlite и др.).
2. Frontend: `valuecell/frontend/package.json` (React, React Router, Tauri API, Zustand, Framer Motion, ECharts и др.).
3. Tauri: `valuecell/frontend/src-tauri/Cargo.toml` (tauri, plugins, serde, reqwest).
4. Конфиги ключей и провайдеров: `valuecell/.env.example`.

---

**Open-Interface**
Tree:
```text
Open-Interface/
├── .git/
├── .github/
├── app/
│   ├── models/
│   ├── resources/
│   ├── utils/
│   ├── app.py
│   ├── core.py
│   ├── interpreter.py
│   ├── llm.py
│   ├── ui.py
│   └── version.py
├── assets/
├── tests/
├── .gitignore
├── .python-version
├── build.py
├── LICENSE.md
├── MEDIA.md
├── README.md
└── requirements.txt
```

Entrypoints:
1. `Open-Interface/app/app.py` — основное приложение.
2. `Open-Interface/build.py` — PyInstaller сборка.

Dependencies:
1. `Open-Interface/requirements.txt` (pyautogui, openai, google-genai, ttkbootstrap, pillow, pyaudio и др.).

---

**Auto-Claude**
Tree:
```text
Auto-Claude/
├── .claude/
├── .design-system/
├── .git/
├── .github/
├── .husky/
├── apps/
│   ├── backend/
│   └── frontend/
├── guides/
├── run.py/
├── scripts/
├── tests/
├── package.json
├── README.md
└── RELEASE.md
```

Entrypoints:
1. `Auto-Claude/apps/backend/run.py` — CLI entrypoint (вызывает `Auto-Claude/apps/backend/cli/main.py`).
2. `Auto-Claude/apps/backend/cli/main.py` — основной CLI.
3. `Auto-Claude/apps/frontend/src/main/index.ts` — Electron main процесс.
4. `Auto-Claude/apps/frontend/src/renderer/main.tsx` — renderer UI.
5. `Auto-Claude/apps/backend/query_memory.py` — CLI для памяти (Graphiti).

Dependencies:
1. Backend: `Auto-Claude/apps/backend/requirements.txt` (claude-agent-sdk, graphiti-core, real_ladybug, pydantic и др.).
2. Frontend: `Auto-Claude/apps/frontend/package.json` (electron, react, xterm, sentry, zustand и др.).
3. Root: `Auto-Claude/package.json` (workspaces + scripts).

---

**computer-agent (Taskhomie)**
Tree:
```text
computer-agent/
├── .git/
├── public/
├── src/
│   ├── components/
│   ├── hooks/
│   ├── stores/
│   ├── types/
│   ├── utils/
│   ├── main.tsx
│   ├── MainWindow.tsx
│   └── VoiceWindow.tsx
├── src-tauri/
│   ├── capabilities/
│   ├── examples/
│   ├── icons/
│   ├── src/
│   ├── Cargo.toml
│   └── tauri.conf.json
├── package.json
├── README.md
└── vite.config.ts
```

Entrypoints:
1. `computer-agent/src-tauri/src/main.rs` — Tauri app entrypoint.
2. `computer-agent/src/main.tsx` — frontend entry.
3. `computer-agent/package.json` — npm scripts (dev/build/tauri).

Dependencies:
1. Frontend: `computer-agent/package.json` (react, framer-motion, tauri api).
2. Rust/Tauri: `computer-agent/src-tauri/Cargo.toml` (tauri, reqwest, enigo, chromiumoxide, deepgram, rusqlite и др.).

---

# Инвентаризация по шаблону

## DeepAnalyze

**Capabilities (что умеет)**
1. Subsystem: OpenAI‑compatible API — чат, файлы, модели, админ‑операции, health‑check, CORS (`DeepAnalyze/API/main.py`, `DeepAnalyze/API/chat_api.py`, `DeepAnalyze/API/file_api.py`, `DeepAnalyze/API/models_api.py`, `DeepAnalyze/API/admin_api.py`).
2. Subsystem: Code execution + artifacts — извлечение `<Code>`, выполнение в subprocess с таймаутом, сбор артефактов, формирование отчета (`DeepAnalyze/API/chat_api.py`, `DeepAnalyze/API/utils.py`).
3. Subsystem: Workspace/файлы — per‑thread workspace, каталог `workspace/_files`, файловый HTTP‑сервер (`DeepAnalyze/API/utils.py`, `DeepAnalyze/API/config.py`, `DeepAnalyze/API/storage.py`).
4. Subsystem: Demo Web UI — Next.js клиент + FastAPI backend для workspace/execute/export (`DeepAnalyze/demo/chat/frontend/app/page.tsx`, `DeepAnalyze/demo/chat/backend.py`).
5. Subsystem: CLI — терминальный интерфейс (EN/中文) поверх API (`DeepAnalyze/demo/cli/api_cli.py`, `DeepAnalyze/demo/cli/api_cli_ZH.py`).
6. Subsystem: Jupyter UI — JupyterLab + MCP (`DeepAnalyze/demo/jupyter/server.py`, `DeepAnalyze/demo/jupyter/mcp_tools.py`).
7. Subsystem: Benchmarks — DSBench, DS‑1000, TableQA, DABStep‑Research (`DeepAnalyze/playground/`).
8. Subsystem: Model tooling — vLLM клиент, квантизация (`DeepAnalyze/deepanalyze.py`, `DeepAnalyze/quantize.py`).
9. Subsystem: Training frameworks — SkyRL и ms‑swift (`DeepAnalyze/deepanalyze/SkyRL/`, `DeepAnalyze/deepanalyze/ms-swift/`).

**Компоненты/сервисы (что реально есть в коде)**
1. FastAPI приложение + роутеры (`DeepAnalyze/API/main.py`).
2. Роутеры: файлы, модели, чат, админ (`DeepAnalyze/API/file_api.py`, `DeepAnalyze/API/models_api.py`, `DeepAnalyze/API/chat_api.py`, `DeepAnalyze/API/admin_api.py`).
3. In‑memory storage + workspace менеджер (`DeepAnalyze/API/storage.py`, `DeepAnalyze/API/utils.py`).
4. HTTP‑файловый сервер (threaded) (`DeepAnalyze/API/utils.py`).
5. Demo backend (workspace CRUD, execute, export) (`DeepAnalyze/demo/chat/backend.py`).
6. Next.js фронтенд (single page) (`DeepAnalyze/demo/chat/frontend/app/page.tsx`).
7. CLI и Jupyter UI (`DeepAnalyze/demo/cli/api_cli.py`, `DeepAnalyze/demo/jupyter/server.py`).
8. Benchmarks и evaluation runners (`DeepAnalyze/playground/**/run_*.py`).
9. Встроенные training submodules (`DeepAnalyze/deepanalyze/SkyRL/`, `DeepAnalyze/deepanalyze/ms-swift/`).

**Интерфейсы**
1. API: `GET /health` (`DeepAnalyze/API/main.py`).
2. API: `GET /v1/models`, `GET /v1/models/{model_id}` (`DeepAnalyze/API/models_api.py`).
3. API: `POST /v1/files`, `GET /v1/files`, `GET /v1/files/{file_id}`, `DELETE /v1/files/{file_id}`, `GET /v1/files/{file_id}/content` (`DeepAnalyze/API/file_api.py`).
4. API: `POST /v1/chat/completions` (streaming и non‑streaming) (`DeepAnalyze/API/chat_api.py`).
5. API: `POST /v1/admin/cleanup-threads`, `GET /v1/admin/threads-stats` (`DeepAnalyze/API/admin_api.py`).
6. Demo backend: `GET /workspace/files`, `GET /workspace/tree`, `DELETE /workspace/file`, `POST /workspace/move`, `DELETE /workspace/dir`, `POST /workspace/upload`, `POST /workspace/upload-to`, `DELETE /workspace/clear`, `POST /execute`, `POST /chat/completions`, `POST /export/report` (`DeepAnalyze/demo/chat/backend.py`).
7. CLI команды: `python demo/cli/api_cli.py`, `python demo/cli/api_cli_ZH.py` (`DeepAnalyze/demo/cli/README.md`).
8. Jupyter: `python demo/jupyter/server.py` (`DeepAnalyze/demo/jupyter/README.md`).
9. Hotkeys: не найдено (поиск в `DeepAnalyze/demo/chat/frontend`, `DeepAnalyze/demo/cli`, `DeepAnalyze/README.md`).

**Data layer**
1. In‑memory store для files/threads/messages (`DeepAnalyze/API/storage.py`).
2. Файлы загружаются в `workspace/_files`, генерируемые артефакты — `workspace/<thread_id>/generated` (`DeepAnalyze/API/config.py`, `DeepAnalyze/API/utils.py`).
3. Workspace per thread (`DeepAnalyze/API/utils.py`).
4. Миграции: не найдено (поиск в `DeepAnalyze/API`, `DeepAnalyze/demo`).

**Интеграции**
1. vLLM OpenAI‑style API (`API_BASE`) через `openai` клиент (`DeepAnalyze/API/chat_api.py`, `DeepAnalyze/API/config.py`).
2. Jupyter MCP сервер (`DeepAnalyze/demo/jupyter/pyproject.toml`, `DeepAnalyze/demo/jupyter/server.py`).
3. Web UI на Next.js (`DeepAnalyze/demo/chat/frontend/package.json`).

**Запуск/деплой**
1. Локальный API: `vllm serve ...` затем `python API/start_server.py` (`DeepAnalyze/API/README.md`).
2. Demo UI: `demo/chat/start.sh` + Next.js frontend (`DeepAnalyze/demo/chat/start.sh`, `DeepAnalyze/demo/chat/frontend/package.json`).
3. CLI: `python demo/cli/api_cli.py` (`DeepAnalyze/demo/cli/README.md`).
4. Docker: `docker/Dockerfile`, `docker/docker-compose.yml` (`DeepAnalyze/docker/README.md`).

**Безопасность**
1. Выполнение кода модели в subprocess без sandbox (только timeout) (`DeepAnalyze/API/utils.py`, `DeepAnalyze/API/chat_api.py`).
2. CORS разрешен всем (`DeepAnalyze/API/main.py`).
3. Нет аутентификации/авторизации на API (`DeepAnalyze/API/main.py`).

**Точки расширения**
1. Добавление моделей: `DeepAnalyze/API/models_api.py`.
2. Изменение tool‑набора: `DeepAnalyze/API/config.py` (`SUPPORTED_TOOLS`).
3. Добавление/расширение demo UI: `DeepAnalyze/demo/chat/frontend`.
4. Добавление бенчмарков: `DeepAnalyze/playground/`.

**Что можно забрать в мой проект — Reusable chunks**
1. `DeepAnalyze/API/` — OpenAI‑compatible API + file handling; deps: FastAPI/uvicorn/openai; cost M.
2. `DeepAnalyze/API/utils.py` — безопасное выполнение кода + workspace utilities; deps: Python stdlib; cost S.
3. `DeepAnalyze/API/storage.py` — in‑memory storage + workspace lifecycle; deps: Python stdlib; cost S.
4. `DeepAnalyze/demo/cli/` — CLI клиент с streaming; deps: requests/openai; cost M.
5. `DeepAnalyze/demo/jupyter/` — Jupyter UI + MCP; deps: jupyter-mcp-server; cost L.
6. `DeepAnalyze/demo/chat/frontend` — готовый Web UI; deps: Next.js stack; cost L.

**Что лучше НЕ тащить**
1. `DeepAnalyze/deepanalyze/ms-swift/` и `DeepAnalyze/deepanalyze/SkyRL/` — тяжелые тренинговые фреймворки и зависимости.
2. `DeepAnalyze/playground/` — бенчмарки, если цель не R&D.
3. `DeepAnalyze/demo/chat/backend.py` — дубль API‑серверной логики, если используешь основной API (`DeepAnalyze/API/`).

**inventory.json**
```json
{
  "capabilities": [
    "OpenAI-compatible API with chat/files/models/admin",
    "Code execution with artifact collection",
    "Web UI (Next.js demo)",
    "CLI and Jupyter UI",
    "Benchmarks and training submodules"
  ],
  "components": [
    "FastAPI app and routers (API/)",
    "In-memory storage + workspace manager",
    "Demo chat backend + Next.js frontend",
    "CLI tools (demo/cli)",
    "Jupyter MCP server (demo/jupyter)",
    "Training frameworks (SkyRL, ms-swift)"
  ],
  "interfaces": [
    "GET /health",
    "GET /v1/models",
    "POST /v1/chat/completions",
    "POST /v1/files",
    "POST /v1/admin/cleanup-threads",
    "Demo: /workspace/*, /execute, /chat/completions, /export/report"
  ],
  "data": [
    "workspace/<thread_id>/",
    "workspace/_files",
    "in-memory dicts for threads/files/messages"
  ],
  "integrations": [
    "vLLM OpenAI-style endpoint",
    "Jupyter MCP server",
    "Next.js frontend"
  ],
  "setup": [
    "Run vLLM then API/start_server.py",
    "Optional demo UI + CLI + Jupyter UI",
    "Dockerfile/docker-compose available"
  ],
  "reuse": [
    {
      "path": "API/",
      "why": "OpenAI-style API + file handling",
      "deps": "fastapi, uvicorn, openai",
      "cost": "M"
    },
    {
      "path": "API/utils.py",
      "why": "Code execution + workspace helpers",
      "deps": "stdlib",
      "cost": "S"
    },
    {
      "path": "demo/cli/",
      "why": "CLI client with streaming",
      "deps": "requests/openai",
      "cost": "M"
    }
  ]
}
```

---

## ValueCell

**Capabilities (что умеет)**
1. Subsystem: Multi‑agent orchestration — Super Agent triage, planner, task executor, event routing, HITL (`valuecell/python/valuecell/core/coordinate/orchestrator.py`, `valuecell/python/valuecell/core/plan`, `valuecell/python/valuecell/core/task`, `valuecell/python/valuecell/core/event`).
2. Subsystem: API сервер — REST + SSE, i18n, агенты, модели, стратегии, watchlist, профили (`valuecell/python/valuecell/server/api/app.py`, `valuecell/python/valuecell/server/api/routers/*`).
3. Subsystem: Streaming агентов (SSE) (`valuecell/python/valuecell/server/api/routers/agent_stream.py`).
4. Subsystem: Агентная платформа — registry через agent cards + YAML‑конфиги (`valuecell/python/configs/agent_cards/`, `valuecell/python/configs/agents/`, `valuecell/docs/CONTRIBUTE_AN_AGENT.md`).
5. Subsystem: Финансовые данные и адаптеры — Yahoo Finance, AKShare, BaoStock (`valuecell/python/valuecell/adapters/`, `valuecell/python/valuecell/server/api/app.py`).
6. Subsystem: Торговое исполнение — ccxt/OKX и стратегия‑агенты (`valuecell/python/valuecell/agents/common/trading/`).
7. Subsystem: Research Agent + Vector DB (LanceDB) (`valuecell/python/valuecell/agents/research_agent/vdb.py`, `valuecell/python/valuecell/utils/db.py`).
8. Subsystem: Web UI + Desktop (Tauri) (`valuecell/frontend/src/routes.ts`, `valuecell/frontend/src-tauri/src/main.rs`).
9. Subsystem: i18n и user profile (`valuecell/python/valuecell/server/api/routers/i18n.py`, `valuecell/python/valuecell/server/api/routers/user_profile.py`).

**Компоненты/сервисы (что реально есть в коде)**
1. FastAPI app factory + middleware + маршруты (`valuecell/python/valuecell/server/api/app.py`).
2. Routers: агенты, стриминг, модели, i18n, стратегии, системные, conversation, user_profile, watchlist (`valuecell/python/valuecell/server/api/routers/*`).
3. Core orchestrator (`valuecell/python/valuecell/core/coordinate/orchestrator.py`).
4. Planner service, task executor, event router (`valuecell/python/valuecell/core/plan`, `valuecell/python/valuecell/core/task`, `valuecell/python/valuecell/core/event`).
5. Conversation/Item/Task stores (SQLite через aiosqlite) (`valuecell/python/valuecell/core/conversation/*`, `valuecell/python/valuecell/core/task/task_store.py`).
6. SQLAlchemy DB модели (agents, assets, strategies, watchlist, profiles) (`valuecell/python/valuecell/server/db/models/*`).
7. Агенты: research, news, prompt_strategy, grid, trading‑subsystem (`valuecell/python/valuecell/agents/*`).
8. Frontend (React Router) + Tauri wrapper (`valuecell/frontend/src/*`, `valuecell/frontend/src-tauri/*`).

**Интерфейсы**
1. API base: `/api/v1` (`valuecell/python/valuecell/server/api/app.py`).
2. System: `GET /api/v1/system/info`, `GET /api/v1/system/health`, `GET /api/v1/system/default-tickers` (`valuecell/python/valuecell/server/api/routers/system.py`).
3. Agents: `GET /api/v1/agents/`, `GET /api/v1/agents/{agent_id}`, `GET /api/v1/agents/by-name/{agent_name}`, `POST /api/v1/agents/{agent_name}/enable` (`valuecell/python/valuecell/server/api/routers/agent.py`).
4. Agent stream (SSE): `POST /api/v1/agents/stream` (`valuecell/python/valuecell/server/api/routers/agent_stream.py`).
5. Conversations: `GET /api/v1/conversations/`, `GET /api/v1/conversations/scheduled-task-results`, `GET /api/v1/conversations/{conversation_id}/history`, `GET /api/v1/conversations/{conversation_id}/scheduled-task-results`, `DELETE /api/v1/conversations/{conversation_id}` (`valuecell/python/valuecell/server/api/routers/conversation.py`).
6. i18n: `GET /api/v1/i18n/config`, `GET /api/v1/i18n/languages`, `GET /api/v1/i18n/timezones`, `PUT /api/v1/i18n/language`, `PUT /api/v1/i18n/timezone`, `POST /api/v1/i18n/detect-language`, `POST /api/v1/i18n/translate`, `POST /api/v1/i18n/format/datetime`, `POST /api/v1/i18n/format/number`, `POST /api/v1/i18n/format/currency`, `GET /api/v1/i18n/user/settings`, `PUT /api/v1/i18n/user/settings` (`valuecell/python/valuecell/server/api/routers/i18n.py`).
7. Models/providers: `GET /api/v1/models/providers`, `GET /api/v1/models/providers/{provider}`, `PUT /api/v1/models/providers/{provider}/config`, `POST /api/v1/models/providers/{provider}/models`, `DELETE /api/v1/models/providers/{provider}/models`, `PUT /api/v1/models/providers/default`, `PUT /api/v1/models/providers/{provider}/default-model`, `POST /api/v1/models/check` (`valuecell/python/valuecell/server/api/routers/models.py`).
8. Strategies: `GET /api/v1/strategies/`, `GET /api/v1/strategies/performance`, `GET /api/v1/strategies/holding`, `GET /api/v1/strategies/portfolio_summary`, `GET /api/v1/strategies/detail`, `GET /api/v1/strategies/holding_price_curve`, `POST /api/v1/strategies/stop` (`valuecell/python/valuecell/server/api/routers/strategy.py`).
9. Strategy prompts: `GET /api/v1/strategy_prompts/`, `POST /api/v1/strategy_prompts/create`, `DELETE /api/v1/strategy_prompts/{prompt_id}` (`valuecell/python/valuecell/server/api/routers/strategy_prompts.py`).
10. Strategy agent: `POST /api/v1/strategy_agent/create`, `POST /api/v1/strategy_agent/test-connection`, `DELETE /api/v1/strategy_agent/delete` (`valuecell/python/valuecell/server/api/routers/strategy_agent.py`).
11. Watchlist: `GET /api/v1/watchlist/asset/search`, `GET /api/v1/watchlist/asset/{ticker}`, `GET /api/v1/watchlist/asset/{ticker}/price`, `GET /api/v1/watchlist/`, `GET /api/v1/watchlist/{watchlist_name}`, `POST /api/v1/watchlist/`, `POST /api/v1/watchlist/asset`, `DELETE /api/v1/watchlist/asset/{ticker}`, `DELETE /api/v1/watchlist/{watchlist_name}`, `PUT /api/v1/watchlist/asset/{ticker}/notes`, `GET /api/v1/watchlist/asset/{ticker}/price/historical` (`valuecell/python/valuecell/server/api/routers/watchlist.py`).
12. User profiles: `POST /api/v1/user/profile`, `GET /api/v1/user/profile`, `GET /api/v1/user/profile/summary`, `GET /api/v1/user/profile/{profile_id}`, `PUT /api/v1/user/profile/{profile_id}`, `DELETE /api/v1/user/profile/{profile_id}` (`valuecell/python/valuecell/server/api/routers/user_profile.py`).
13. Task control: `POST /api/v1/tasks/{task_id}/cancel` (`valuecell/python/valuecell/server/api/routers/task.py`).
14. UI routes: `/home`, `/home/stock/:stockId`, `/market`, `/agent/:agentName`, `/agent/:agentName/config`, `/setting`, `/setting/general`, `/setting/memory` (`valuecell/frontend/src/routes.ts`).
15. Hotkeys: Ctrl/Cmd+B toggles sidebar (`valuecell/frontend/src/components/ui/sidebar.tsx`).

**Data layer**
1. SQLAlchemy DB (по умолчанию SQLite): `VALUECELL_DATABASE_URL` → `valuecell.db` (`valuecell/python/valuecell/server/db/connection.py`, `valuecell/python/valuecell/server/config/settings.py`).
2. Таблицы: agents/assets/strategies/watchlist/user_profile и др. (`valuecell/python/valuecell/server/db/models/*`).
3. Conversation/Item/Task stores в SQLite (aiosqlite), схемы создаются лениво (`valuecell/python/valuecell/core/conversation/conversation_store.py`, `valuecell/python/valuecell/core/conversation/item_store.py`, `valuecell/python/valuecell/core/task/task_store.py`).
4. Vector DB: LanceDB (путь через `resolve_lancedb_uri`) (`valuecell/python/valuecell/agents/research_agent/vdb.py`, `valuecell/python/valuecell/utils/db.py`).
5. Миграции: отдельного инструмента миграций не найдено (поиск в `valuecell/python/valuecell/server/db`, `valuecell/python/valuecell/core`).

**Интеграции**
1. LLM провайдеры: OpenRouter, OpenAI, Azure OpenAI, Google, SiliconFlow, DashScope, OpenAI‑compatible (`valuecell/.env.example`, `valuecell/python/configs/providers/*`).
2. A2A SDK для удалённых агентов (`valuecell/python/pyproject.toml`).
3. Рыночные данные: yfinance, AKShare, BaoStock (`valuecell/python/valuecell/server/api/app.py`, `valuecell/python/pyproject.toml`).
4. Трейдинг: ccxt, OKX/Hyperliquid/биржи через агенты (`valuecell/python/valuecell/agents/common/trading/`, `valuecell/python/pyproject.toml`).
5. Веб‑скрейпинг: crawl4ai, edgartools (`valuecell/python/pyproject.toml`).
6. Desktop wrapper: Tauri (`valuecell/frontend/src-tauri/Cargo.toml`).

**Запуск/деплой**
1. `./start.sh` и `./start.ps1` (установка bun/uv, запуск frontend+backend) (`valuecell/start.sh`).
2. Backend: `uv run python -m valuecell.server.main` (`valuecell/python/valuecell/server/main.py`).
3. DB init: `python -m valuecell.server.db.init_db` (`valuecell/python/valuecell/server/db/init_db.py`).
4. Frontend: `bun run dev` (`valuecell/frontend/package.json`).
5. Tauri сборка: `frontend/src-tauri` (`valuecell/frontend/src-tauri/Cargo.toml`).

**Безопасность**
1. Ключи LLM и биржевые ключи хранятся в системном `.env` (локально) (`valuecell/start.sh`, `valuecell/.env.example`).
2. CORS разрешён всем (`valuecell/python/valuecell/server/api/app.py`).
3. Live‑торговля через ccxt требует строгих ограничений (код реально вызывает исполнение) (`valuecell/python/valuecell/agents/common/trading/execution/ccxt_trading.py`).

**Точки расширения**
1. Новый агент: структура + `__main__.py` + YAML + agent card (`valuecell/docs/CONTRIBUTE_AN_AGENT.md`, `valuecell/python/configs/agents/`, `valuecell/python/configs/agent_cards/`).
2. Новые провайдеры LLM: `valuecell/python/configs/providers/`.
3. Новые источники данных: `valuecell/python/valuecell/adapters/`.

**Что можно забрать в мой проект — Reusable chunks**
1. `valuecell/python/valuecell/core/coordinate/` — оркестратор (HITL, streaming, re‑entry); deps: aiosqlite, pydantic; cost M.
2. `valuecell/python/valuecell/core/event/` — routing/aggregation событий; cost M.
3. `valuecell/python/valuecell/core/conversation/` и `core/task/` — SQLite‑хранилища; deps: aiosqlite; cost S/M.
4. `valuecell/python/valuecell/server/api/routers/agent_stream.py` — SSE стриминг; deps: FastAPI; cost M.
5. `valuecell/python/configs/agent_cards` + `configs/agents` — registry + config; cost M.

**Что лучше НЕ тащить**
1. `valuecell/python/valuecell/agents/common/trading/` — доменно‑специфичные и рискованные торговые модули.
2. `valuecell/python/valuecell/server/db/models/strategy*` — если нет фин‑стратегий.
3. Tauri слой `valuecell/frontend/src-tauri/` — если не нужен desktop.

**inventory.json**
```json
{
  "capabilities": [
    "Multi-agent orchestration with planning/HITL",
    "REST + SSE API server",
    "Agent registry via cards/configs",
    "Market data + trading integrations",
    "Web UI + Tauri desktop shell"
  ],
  "components": [
    "FastAPI app + routers",
    "Core orchestrator (plan/task/event/super_agent)",
    "SQLite conversation/task stores",
    "SQLAlchemy domain DB models",
    "Agents and adapters",
    "Frontend + Tauri wrapper"
  ],
  "interfaces": [
    "/api/v1/agents/*",
    "/api/v1/agents/stream (SSE)",
    "/api/v1/conversations/*",
    "/api/v1/models/*",
    "/api/v1/strategies/*",
    "/api/v1/watchlist/*"
  ],
  "data": [
    "SQLite valuecell.db (system app dir)",
    "SQLite conversation/task stores (aiosqlite)",
    "LanceDB knowledge base"
  ],
  "integrations": [
    "OpenRouter/OpenAI/Azure/Google providers",
    "yfinance/akshare/baostock data",
    "ccxt exchange execution",
    "A2A SDK"
  ],
  "setup": [
    "start.sh/start.ps1",
    "uv run python -m valuecell.server.main",
    "DB init via valuecell.server.db.init_db"
  ],
  "reuse": [
    {
      "path": "python/valuecell/core/coordinate/",
      "why": "orchestrator + HITL + streaming",
      "deps": "aiosqlite, pydantic",
      "cost": "M"
    },
    {
      "path": "python/valuecell/core/conversation/",
      "why": "conversation persistence",
      "deps": "aiosqlite",
      "cost": "S"
    },
    {
      "path": "python/valuecell/server/api/routers/agent_stream.py",
      "why": "SSE agent streaming API",
      "deps": "fastapi",
      "cost": "M"
    }
  ]
}
```

---

## Open-Interface

**Capabilities (что умеет)**
1. Subsystem: LLM‑driven компьютерное управление — LLM → JSON steps → pyautogui (`Open-Interface/app/llm.py`, `Open-Interface/app/interpreter.py`).
2. Subsystem: Screen/context injection — скриншоты, контекст ОС (`Open-Interface/app/utils/screen.py`, `Open-Interface/app/llm.py`).
3. Subsystem: Desktop UI — Tkinter/ttkbootstrap, окно настроек и advanced settings (`Open-Interface/app/ui.py`).
4. Subsystem: Multi‑provider LLM — OpenAI/GPT‑4o, GPT‑4V, Gemini, OpenAI‑compatible base_url (`Open-Interface/app/models/factory.py`, `Open-Interface/app/llm.py`).
5. Subsystem: Packaging — PyInstaller build (`Open-Interface/build.py`).

**Компоненты/сервисы (что реально есть в коде)**
1. App entry + glue: `Open-Interface/app/app.py`.
2. Core: `Open-Interface/app/core.py` (циклическое выполнение шагов).
3. Interpreter: `Open-Interface/app/interpreter.py` (pyautogui функции).
4. LLM wrapper + ModelFactory: `Open-Interface/app/llm.py`, `Open-Interface/app/models/factory.py`.
5. Settings persistence: `Open-Interface/app/utils/settings.py`.
6. UI: `Open-Interface/app/ui.py`.

**Интерфейсы**
1. UI окна: MainWindow, SettingsWindow, AdvancedSettingsWindow (`Open-Interface/app/ui.py`).
2. LLM протокол: JSON schema steps/done, описан в коде и `context.txt` (`Open-Interface/app/llm.py`, `Open-Interface/app/resources/context.txt`).
3. HTTP API: не найдено (поиск в `Open-Interface/app`, `Open-Interface/README.md`).
4. CLI: не найдено (поиск в `Open-Interface/app`, `Open-Interface/README.md`).
5. Hotkeys (глобальные): не найдено (поиск в `Open-Interface/app`).

**Data layer**
1. Настройки в `~/.open-interface/settings.json` (base64 API key) (`Open-Interface/app/utils/settings.py`).
2. БД/миграции: не найдено (поиск в `Open-Interface/app`, `Open-Interface/tests`).

**Интеграции**
1. OpenAI API (`openai` SDK) + OpenAI‑compatible base_url (`Open-Interface/app/llm.py`, `Open-Interface/app/models/gpt4o.py`, `Open-Interface/app/models/gpt4v.py`).
2. Google Gemini (`Open-Interface/app/models/gemini.py`).
3. OS input control: PyAutoGUI (`Open-Interface/app/interpreter.py`).

**Запуск/деплой**
1. Локально: `python app/app.py` (`Open-Interface/app/app.py`, `Open-Interface/README.md`).
2. Сборка: `python build.py` (`Open-Interface/build.py`).

**Безопасность**
1. API ключ хранится в `~/.open-interface/settings.json` (base64, не шифрование) (`Open-Interface/app/utils/settings.py`).
2. Требует системных разрешений на управление клавиатурой/мышью и screen recording (описано в `Open-Interface/README.md`).

**Точки расширения**
1. Новый провайдер: добавить класс в `Open-Interface/app/models/` и зарегистрировать в `Open-Interface/app/models/factory.py`.
2. Новый набор действий: изменить `Open-Interface/app/interpreter.py` и `Open-Interface/app/resources/context.txt`.
3. UI расширения: `Open-Interface/app/ui.py`.

**Что можно забрать в мой проект — Reusable chunks**
1. `Open-Interface/app/llm.py` + `app/models/*` — LLM JSON‑инструкции; deps: openai/google‑genai; cost M.
2. `Open-Interface/app/interpreter.py` — слой выполнения действий через pyautogui; deps: pyautogui; cost S.
3. `Open-Interface/app/utils/settings.py` — простой local settings store; deps: stdlib; cost S.
4. `Open-Interface/app/ui.py` — готовый desktop UI‑скелет; deps: ttkbootstrap; cost M.

**Что лучше НЕ тащить**
1. `Open-Interface/build.py` — если не используешь PyInstaller.
2. PyAutoGUI слой — если в проекте планируется нативное управление из Rust/Tauri (см. Taskhomie).

**inventory.json**
```json
{
  "capabilities": [
    "LLM-driven computer control via pyautogui",
    "Desktop UI with settings",
    "Multi-provider LLM (OpenAI/Gemini/custom)",
    "PyInstaller packaging"
  ],
  "components": [
    "Core loop (core.py)",
    "Interpreter (pyautogui)",
    "LLM wrapper + ModelFactory",
    "Settings store",
    "Tkinter UI"
  ],
  "interfaces": [
    "UI windows (main/settings/advanced)",
    "LLM JSON step schema in context.txt"
  ],
  "data": [
    "~/.open-interface/settings.json"
  ],
  "integrations": [
    "OpenAI API",
    "Google Gemini API",
    "PyAutoGUI"
  ],
  "setup": [
    "python app/app.py",
    "build.py for PyInstaller"
  ],
  "reuse": [
    {
      "path": "app/interpreter.py",
      "why": "pyautogui execution layer",
      "deps": "pyautogui",
      "cost": "S"
    },
    {
      "path": "app/llm.py",
      "why": "LLM step protocol",
      "deps": "openai/google-genai",
      "cost": "M"
    }
  ]
}
```

---

## Auto-Claude

**Capabilities (что умеет)**
1. Subsystem: автономный build‑цикл — planning → execution → QA → review/merge (`Auto-Claude/apps/backend/cli/main.py`, `Auto-Claude/apps/backend/qa_loop.py`, `Auto-Claude/apps/backend/merge/`).
2. Subsystem: worktree‑изоляция и управление git (`Auto-Claude/apps/backend/worktree.py`, `Auto-Claude/apps/backend/workspace.py`).
3. Subsystem: память/knowledge graph (Graphiti + LadybugDB) (`Auto-Claude/apps/backend/integrations/graphiti/config.py`, `Auto-Claude/apps/backend/memory/`).
4. Subsystem: desktop UI (Electron) — kanban, terminals, insights, roadmap, changelog (`Auto-Claude/apps/frontend/src/renderer/components/Sidebar.tsx`).
5. Subsystem: интеграции (Linear/GitHub/GitLab) (`Auto-Claude/apps/backend/integrations/linear/`, `Auto-Claude/apps/backend/runners/gitlab/`, `Auto-Claude/apps/backend/runners/github/`).
6. Subsystem: security scanning (`Auto-Claude/apps/backend/scan_secrets.py`, `Auto-Claude/apps/backend/security/`).

**Компоненты/сервисы (что реально есть в коде)**
1. CLI entry + команды (`Auto-Claude/apps/backend/run.py`, `Auto-Claude/apps/backend/cli/main.py`).
2. Планировщик/спецификации: `Auto-Claude/apps/backend/spec/`, `Auto-Claude/apps/backend/implementation_plan/`.
3. QA pipeline: `Auto-Claude/apps/backend/qa/`, `Auto-Claude/apps/backend/qa_loop.py`.
4. Merge/review: `Auto-Claude/apps/backend/merge/`, `Auto-Claude/apps/backend/review/`.
5. Memory layer: `Auto-Claude/apps/backend/memory/`, `Auto-Claude/apps/backend/integrations/graphiti/`.
6. Git worktrees: `Auto-Claude/apps/backend/worktree.py`, `Auto-Claude/apps/backend/workspace.py`.
7. Electron main/renderer: `Auto-Claude/apps/frontend/src/main/index.ts`, `Auto-Claude/apps/frontend/src/renderer/main.tsx`.

**Интерфейсы**
1. CLI: `--list`, `--spec`, `--merge`, `--review`, `--discard`, `--qa`, `--qa-status`, `--review-status`, `--list-worktrees`, `--cleanup-worktrees`, `--create-pr`, `--followup` (`Auto-Claude/apps/backend/cli/main.py`).
2. UI навигация (горячие клавиши): K=Kanban, A=Terminals, N=Insights, D=Roadmap, I=Ideation, L=Changelog, C=Context, M=Agent Tools, W=Worktrees, G=GitHub Issues, P=GitHub PRs, B=GitLab Issues, R=GitLab MRs (`Auto-Claude/apps/frontend/src/renderer/components/Sidebar.tsx`).
3. Global UI shortcut: Cmd/Ctrl+T добавить проект (`Auto-Claude/apps/frontend/src/renderer/App.tsx`).
4. Терминал shortcuts (copy/paste и табы) (`Auto-Claude/apps/frontend/src/renderer/components/terminal/useXterm.ts`, `Auto-Claude/apps/frontend/src/renderer/components/SortableProjectTab.tsx`).
5. HTTP API: не найдено (поиск в `Auto-Claude/apps/backend` по FastAPI/uvicorn/flask).

**Data layer**
1. Graphiti/LadybugDB в `~/.auto-claude/memories` (по умолчанию) (`Auto-Claude/apps/backend/integrations/graphiti/config.py`, `Auto-Claude/apps/backend/.env.example`).
2. Проектное состояние в `.auto-claude/` внутри проекта (specs, worktrees, roadmap, gitlab/github state) (`Auto-Claude/apps/backend/init.py`, `Auto-Claude/apps/backend/cli/utils.py`).
3. Миграции БД: отдельные миграции не найдены (поиск в `Auto-Claude/apps/backend`).

**Интеграции**
1. Claude Code OAuth (через CLI/Keychain) (`Auto-Claude/apps/backend/.env.example`, `Auto-Claude/apps/backend/core/auth.py`).
2. Graphiti memory: OpenAI/Anthropic/Azure/Ollama/Google/OpenRouter (`Auto-Claude/apps/backend/integrations/graphiti/config.py`).
3. Linear integration (`Auto-Claude/apps/backend/integrations/linear/`).
4. GitHub/GitLab runners (`Auto-Claude/apps/backend/runners/github/`, `Auto-Claude/apps/backend/runners/gitlab/`).
5. Sentry (frontend) (`Auto-Claude/apps/frontend/package.json`).

**Запуск/деплой**
1. Backend CLI: `python apps/backend/run.py --spec 001` (`Auto-Claude/apps/backend/run.py`).
2. Frontend: `npm run dev` или `npm start` в `apps/frontend` (`Auto-Claude/apps/frontend/package.json`).
3. Упаковка: `npm run package:*` (`Auto-Claude/apps/frontend/package.json`).

**Безопасность**
1. OAuth токены хранятся в системных секрет‑сторах (описано в `.env.example`) (`Auto-Claude/apps/backend/.env.example`).
2. Командные операции в worktree; `.auto-claude/` исключается из git‑merge (`Auto-Claude/apps/backend/worktree.py`).
3. Есть сканер секретов (`Auto-Claude/apps/backend/scan_secrets.py`).

**Точки расширения**
1. Новые агенты/фазы: `Auto-Claude/apps/backend/agents/`, `Auto-Claude/apps/backend/spec/`.
2. Memory providers: `Auto-Claude/apps/backend/integrations/graphiti/`.
3. UI навигация и вкладки: `Auto-Claude/apps/frontend/src/renderer/components/Sidebar.tsx`.

**Что можно забрать в мой проект — Reusable chunks**
1. `Auto-Claude/apps/backend/worktree.py` + `workspace.py` — изоляция в git worktrees; deps: git; cost M.
2. `Auto-Claude/apps/backend/qa/` + `qa_loop.py` — QA pipeline; deps: claude-agent-sdk; cost L.
3. `Auto-Claude/apps/backend/integrations/graphiti/` — память (graph DB); deps: graphiti-core, real_ladybug; cost L.
4. `Auto-Claude/apps/backend/cli/main.py` — готовый CLI‑каркас; deps: stdlib; cost M.
5. `Auto-Claude/apps/frontend/src/renderer/components/Sidebar.tsx` — горячие клавиши + навигация; deps: React; cost M.

**Что лучше НЕ тащить**
1. `Auto-Claude/apps/frontend` — тяжелый Electron стек, если нужен легкий desktop.
2. `Auto-Claude/apps/backend/qa/` — сложный QA‑контур, если MVP без автотестов.
3. `Auto-Claude/apps/backend/integrations/graphiti/` — если не нужна долговременная память.

**inventory.json**
```json
{
  "capabilities": [
    "Autonomous spec-based build pipeline",
    "Worktree isolation and merge/review",
    "Graph memory integration",
    "Desktop Electron UI",
    "GitHub/GitLab/Linear integrations"
  ],
  "components": [
    "Backend CLI and orchestration modules",
    "QA and review pipelines",
    "Worktree/workspace manager",
    "Graphiti memory integration",
    "Electron main/renderer UI"
  ],
  "interfaces": [
    "CLI flags (--spec, --merge, --review, --qa...)",
    "UI hotkeys for navigation and terminals"
  ],
  "data": [
    "~/.auto-claude/memories",
    ".auto-claude/ project state (specs/worktrees)"
  ],
  "integrations": [
    "Claude Code OAuth",
    "Graphiti providers (OpenAI/Anthropic/...)",
    "GitHub/GitLab/Linear"
  ],
  "setup": [
    "python apps/backend/run.py --spec <id>",
    "npm run dev/start in apps/frontend"
  ],
  "reuse": [
    {
      "path": "apps/backend/worktree.py",
      "why": "git worktree isolation",
      "deps": "git",
      "cost": "M"
    },
    {
      "path": "apps/backend/integrations/graphiti/",
      "why": "persistent memory layer",
      "deps": "graphiti-core, real_ladybug",
      "cost": "L"
    }
  ]
}
```

---

## computer-agent (Taskhomie)

**Capabilities (что умеет)**
1. Subsystem: Computer control — мышь/клавиатура/скриншоты (Enigo + xcap) (`computer-agent/src-tauri/src/computer.rs`, `computer-agent/src-tauri/src/agent.rs`).
2. Subsystem: Browser automation — CDP через Chromiumoxide, отдельный профиль (`computer-agent/src-tauri/src/browser.rs`, `computer-agent/src-tauri/src/permissions.rs`).
3. Subsystem: Bash execution — исполнение команд (`computer-agent/src-tauri/src/bash.rs`).
4. Subsystem: LLM tool‑use — Anthropic API + computer tool (`computer-agent/src-tauri/src/api.rs`, `computer-agent/src-tauri/src/agent.rs`).
5. Subsystem: Voice — STT Deepgram + TTS ElevenLabs (`computer-agent/src-tauri/src/voice.rs`, `computer-agent/src-tauri/src/permissions.rs`).
6. Subsystem: Desktop UI (Tauri) — main/voice окна, help/spotlight режимы (`computer-agent/src/MainWindow.tsx`, `computer-agent/src/VoiceWindow.tsx`).
7. Subsystem: Conversation persistence — SQLite в app data (`computer-agent/src-tauri/src/storage.rs`).
8. Subsystem: Global hotkeys — push‑to‑talk и UI переключения (`computer-agent/src-tauri/src/main.rs`).

**Компоненты/сервисы (что реально есть в коде)**
1. Tauri main + команды (`computer-agent/src-tauri/src/main.rs`).
2. Agent runtime (`computer-agent/src-tauri/src/agent.rs`).
3. Anthropic API client (`computer-agent/src-tauri/src/api.rs`).
4. Computer control (`computer-agent/src-tauri/src/computer.rs`).
5. Browser control (`computer-agent/src-tauri/src/browser.rs`).
6. Bash executor (`computer-agent/src-tauri/src/bash.rs`).
7. Permissions/OS integration (`computer-agent/src-tauri/src/permissions.rs`).
8. SQLite storage (`computer-agent/src-tauri/src/storage.rs`).
9. Voice services (`computer-agent/src-tauri/src/voice.rs`).
10. Frontend UI (`computer-agent/src/MainWindow.tsx`, `computer-agent/src/VoiceWindow.tsx`, `computer-agent/src/components/*`).

**Интерфейсы**
1. Tauri commands (часть): `set_api_key`, `check_api_key`, `run_agent`, `stop_agent`, `is_agent_running`, `set_window_state`, `show_voice_window`, `hide_voice_window`, `hide_main_window`, `capture_screen_for_help` (`computer-agent/src-tauri/src/main.rs`).
2. Storage commands: `list_conversations`, `load_conversation`, `create_conversation`, `save_conversation`, `delete_conversation`, `search_conversations`, `set_conversation_voice_mode` (`computer-agent/src-tauri/src/main.rs`).
3. Permissions commands: `check_permissions`, `request_permission`, `open_permission_settings`, `get_browser_profile_status`, `clear_domain_cookies`, `open_browser_profile`, `open_browser_profile_url`, `reset_browser_profile`, `get_api_key_status`, `get_voice_settings`, `save_voice_settings`, `save_api_key` (`computer-agent/src-tauri/src/permissions.rs`).
4. Voice commands: `start_voice`, `stop_voice`, `is_voice_running`, `start_ptt`, `stop_ptt`, `is_ptt_running` (`computer-agent/src-tauri/src/main.rs`).
5. Tauri events (emit): `agent:started`, `agent:stopped`, `agent-update`, `agent-stream`, `agent:action`, `agent:bash`, `agent:browser_tool`, `agent:speak`, `browser:needs-restart`, `ptt:recording`, `ptt:result`, `hotkey-help`, `hotkey-spotlight` (`computer-agent/src-tauri/src/agent.rs`, `computer-agent/src-tauri/src/main.rs`, `computer-agent/src-tauri/src/voice.rs`).
6. UI modes: idle/expanded/running/help/voiceResponse/spotlight (`computer-agent/src/MainWindow.tsx`).
7. Hotkeys: Cmd+Shift+H (help), Cmd+Shift+Space (spotlight), Cmd+Shift+S (stop), Cmd+Shift+Q (quit), Ctrl+Shift+C/B (PTT computer/browser) (`computer-agent/src-tauri/src/main.rs`).

**Data layer**
1. SQLite DB в app data: `taskhomie/conversations.db` (`computer-agent/src-tauri/src/storage.rs`).
2. Схема: таблица `conversations` с messages_json, turn_usage_json, voice_mode (`computer-agent/src-tauri/src/storage.rs`).
3. Chrome профиль: `~/.taskhomie-chrome` (`computer-agent/src-tauri/src/permissions.rs`).
4. Миграции: есть миграция add column `voice_mode` (DDL) (`computer-agent/src-tauri/src/storage.rs`).

**Интеграции**
1. Anthropic API (`computer-agent/src-tauri/src/api.rs`).
2. Deepgram STT (`computer-agent/src-tauri/src/voice.rs`).
3. ElevenLabs TTS (`computer-agent/src-tauri/src/voice.rs`, `computer-agent/src-tauri/src/permissions.rs`).
4. Chrome DevTools Protocol (`computer-agent/src-tauri/src/browser.rs`).
5. OS permissions: accessibility/screen recording/microphone (macOS) (`computer-agent/src-tauri/src/permissions.rs`).

**Запуск/деплой**
1. Локально: `npm install` и `npm run tauri dev` (`computer-agent/README.md`, `computer-agent/package.json`).
2. Build: `npm run tauri build` (`computer-agent/package.json`).

**Безопасность**
1. Требует широких OS разрешений (screen recording/accessibility/mic) (`computer-agent/src-tauri/src/permissions.rs`).
2. Хранение ключей в `.env` и env vars (`computer-agent/src-tauri/src/main.rs`, `computer-agent/src-tauri/src/permissions.rs`).
3. Запуск bash команд моделью (`computer-agent/src-tauri/src/bash.rs`, `computer-agent/src-tauri/src/agent.rs`).

**Точки расширения**
1. Новые tool‑интерфейсы: расширение `computer-agent/src-tauri/src/api.rs` и `agent.rs`.
2. Новые UI режимы/панели: `computer-agent/src/MainWindow.tsx`, `computer-agent/src/VoiceWindow.tsx`.
3. Данные/персистенс: `computer-agent/src-tauri/src/storage.rs`.

**Что можно забрать в мой проект — Reusable chunks**
1. `computer-agent/src-tauri/src/agent.rs` — runtime agent + tool routing; deps: reqwest, tokio; cost L.
2. `computer-agent/src-tauri/src/computer.rs` — desktop control; deps: enigo/xcap; cost M.
3. `computer-agent/src-tauri/src/browser.rs` — CDP automation; deps: chromiumoxide; cost M/L.
4. `computer-agent/src-tauri/src/storage.rs` — SQLite conversation store; deps: rusqlite; cost S.
5. `computer-agent/src/MainWindow.tsx` — UI state‑machine и режимы; deps: React; cost M.

**Что лучше НЕ тащить**
1. Voice stack (`voice.rs`) если MVP без голоса.
2. CDP браузер + отдельный Chrome профиль, если нужен только OS‑контроль.

**inventory.json**
```json
{
  "capabilities": [
    "Computer control (mouse/keyboard/screenshot)",
    "Browser automation via CDP",
    "Bash execution",
    "Voice STT/TTS",
    "Tauri desktop UI",
    "Conversation persistence (SQLite)"
  ],
  "components": [
    "Agent runtime (agent.rs)",
    "Anthropic API client (api.rs)",
    "Computer/Browser/Bash tools",
    "Permissions manager",
    "SQLite storage",
    "React UI windows"
  ],
  "interfaces": [
    "Tauri commands (run_agent, stop_agent, storage, permissions, voice)",
    "Tauri events (agent:*, ptt:*, hotkey-*)",
    "Global shortcuts (Cmd+Shift+H/Space/S/Q, Ctrl+Shift+C/B)"
  ],
  "data": [
    "SQLite conversations.db",
    "Chrome profile ~/.taskhomie-chrome"
  ],
  "integrations": [
    "Anthropic API",
    "Deepgram STT",
    "ElevenLabs TTS",
    "Chromiumoxide (CDP)"
  ],
  "setup": [
    "npm run tauri dev",
    "npm run tauri build"
  ],
  "reuse": [
    {
      "path": "src-tauri/src/computer.rs",
      "why": "OS control implementation",
      "deps": "enigo, xcap",
      "cost": "M"
    },
    {
      "path": "src-tauri/src/storage.rs",
      "why": "SQLite conversation store",
      "deps": "rusqlite",
      "cost": "S"
    }
  ]
}
```

---

# Capability Matrix

| Capability | DeepAnalyze | ValueCell | Open-Interface | Auto-Claude | computer-agent |
|---|---|---|---|---|---|
| Desktop shell | none | native | native | native | native |
| Agent orchestrator | partial | native | none | native | partial |
| Computer control | none | none | native | none | native |
| Browser automation | none | partial | partial | partial | native |
| Memory KB / persistence | partial | native | none | native | partial |
| Plugin/agent system | partial | native | partial | native | partial |
| Eval/benchmarks | native | none | none | partial (tests) | none |
| Voice (STT/TTS) | none | none | none | none | native |
| LLM multi-provider | partial | native | native | partial | partial |
| Streaming API | native | native | none | none | none |
| Web UI | native | native | none | none | none |
| CLI | native | partial | none | native | none |
| Jupyter UI | native | none | none | none | none |
| Trading/exchange | none | native | none | none | none |
| Code execution sandbox | native | partial | none | native | native |

---

# Dedup Map (что дублируется и что брать базой)

1. Computer control: `Open-Interface/app/interpreter.py` (pyautogui) vs `computer-agent/src-tauri/src/computer.rs` (enigo/xcap). База для production: Taskhomie (Rust/Tauri) — нативнее и быстрее; Open‑Interface можно брать как простой Python‑прототип.
2. Desktop shell: Tauri (`valuecell/frontend/src-tauri/*`, `computer-agent/src-tauri/*`) vs Electron (`Auto-Claude/apps/frontend`). База: Tauri, если нужен легкий desktop; Electron — если нужны встроенные терминалы/сложные панели.
3. Orchestration: `valuecell/python/valuecell/core/*` vs `Auto-Claude/apps/backend/*`. База: ValueCell, если нужен API+SSE; Auto-Claude, если фокус на автономной разработке и worktrees.
4. Memory: ValueCell (LanceDB + SQLite stores) vs Auto‑Claude (Graphiti/LadybugDB). База: Graphiti для долговременной граф‑памяти; ValueCell — если нужен быстрый vector‑search для документов.
5. Web UI: `DeepAnalyze/demo/chat/frontend` vs `valuecell/frontend`. База: ValueCell, если нужен многоэкранный продукт; DeepAnalyze — если нужен только чат‑панель и файловый explorer.

---

# MVP-cut (минимальный набор модулей для 1‑й версии)

Ниже — минимальный набор модулей, который технически связывается без лишнего, без доменной специфики (финансы/трейдинг) и без тяжелых UI‑стеков.

1. Agent runtime + tool layer: `computer-agent/src-tauri/src/agent.rs`, `computer-agent/src-tauri/src/computer.rs`, `computer-agent/src-tauri/src/bash.rs`, `computer-agent/src-tauri/src/browser.rs`.
2. Persistence: `computer-agent/src-tauri/src/storage.rs` (SQLite история диалогов).
3. UI shell: `computer-agent/src/MainWindow.tsx` + `computer-agent/src/VoiceWindow.tsx` (один минимальный desktop UI с help/spotlight режимами).
4. Orchestration (если нужна многошаговая логика поверх tool‑use): `valuecell/python/valuecell/core/coordinate/` + `valuecell/python/valuecell/core/event/` + `valuecell/python/valuecell/core/task/` (можно подключить поверх, не таща финансовые модули).

Если MVP должен быть только про data science — вместо пункта 4 можно взять `DeepAnalyze/API/` и `demo/chat/frontend` как готовую связку API+UI.
