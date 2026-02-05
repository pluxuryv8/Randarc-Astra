# API Randarc-Astra

EN kept: пути API — публичный контракт.

## Запуски

- `POST /api/v1/projects/{project_id}/runs` — создать запуск
- `POST /api/v1/runs/{run_id}/plan` — построить план
- `POST /api/v1/runs/{run_id}/start` — старт
- `POST /api/v1/runs/{run_id}/cancel` — остановка
- `POST /api/v1/runs/{run_id}/pause` — пауза
- `POST /api/v1/runs/{run_id}/resume` — продолжить
- `GET /api/v1/runs/{run_id}` — состояние
- `GET /api/v1/runs/{run_id}/snapshot` — снимок состояния
- `GET /api/v1/runs/{run_id}/events` — поток событий (SSE)

## Артефакты

- `GET /api/v1/artifacts/{artifact_id}/download` — скачивание файла

## Навыки

- `GET /api/v1/skills` — список
- `GET /api/v1/skills/{skill_name}/manifest` — манифест
- `POST /api/v1/skills/reload` — перезагрузка (dev)

## Подтверждения

- `GET /api/v1/runs/{run_id}/approvals`
- `POST /api/v1/approvals/{approval_id}/approve`
- `POST /api/v1/approvals/{approval_id}/reject`
