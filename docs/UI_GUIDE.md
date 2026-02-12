# UI Guide (Astra Desktop)

## Layout
- Sidebar: список runs, поиск, кнопки Memory/Reminders/Settings. См. `apps/desktop/src/MainApp.tsx`.
- Main: чат, статус агента, поле ввода, быстрые действия. См. `apps/desktop/src/MainApp.tsx`.
- Inspector: вкладки Steps/Events/Approvals/Metrics (панель справа). См. `apps/desktop/src/MainApp.tsx`.
- Memory/Settings: панели в правой колонке. См. `apps/desktop/src/ui/MemoryPanel.tsx`, `apps/desktop/src/ui/SettingsPanel.tsx`.
- Reminders: панель напоминаний `apps/desktop/src/ui/RemindersPanel.tsx`.
- Overlay (маленькое окно): см. `apps/desktop/src/OverlayApp.tsx` (открывается как `?view=overlay`).

## Data Flow
- Projects: `GET /api/v1/projects` через `apps/desktop/src/api.ts:listProjects`.
- Runs list: `GET /api/v1/projects/{project_id}/runs` через `apps/desktop/src/api.ts:listRuns`.
- Create run: `POST /api/v1/projects/{project_id}/runs` через `apps/desktop/src/api.ts:createRun`.
- Snapshot: `GET /api/v1/runs/{run_id}/snapshot` через `apps/desktop/src/api.ts:getSnapshot`.
- Approvals: `POST /api/v1/approvals/{id}/approve|reject` через `apps/desktop/src/api.ts:approve|reject`.
- Memory: `GET /api/v1/memory/list`, `DELETE /api/v1/memory/{id}` через `apps/desktop/src/api.ts`.

## Events (SSE)
- Endpoint: `GET /api/v1/runs/{run_id}/events`.
- Подписка и дедуп: `apps/desktop/src/MainApp.tsx` + `apps/desktop/src/ui/utils.ts:mergeEvents`.
- Буфер ограничен `EVENT_BUFFER_LIMIT`.

## UI State
- Выбранный run хранится в `localStorage` (`astra_last_run_id`) и восстанавливается при запуске.
- Inspector/Memory/Settings управляются через `rightPanel` в `apps/desktop/src/MainApp.tsx`.

## Style Tokens
- Токены и базовые стили: `apps/desktop/src/app.css`.
- Основные переменные: `--bg`, `--surface`, `--border`, `--text`, `--muted`, `--ok`, `--warn`, `--error`.

## Debugging
- Если SSE не приходит: проверь `apiBase` и доступность `/runs/{id}/events`.
- Если run не выбирается: проверь `listRuns` и `localStorage` ключ `astra_last_run_id`.
- Если approvals не отображаются: проверь snapshot `/runs/{id}/snapshot` и поле `approvals`.
