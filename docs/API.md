# API Reference (Current)

Base path: `/api/v1`.

## Auth

- `GET /auth/status` (`apps/api/routes/auth.py:13`)
- `POST /auth/bootstrap` (`apps/api/routes/auth.py:24`)

Auth middleware behavior is in `apps/api/auth.py:76`.

## Projects

- `POST /projects` (`apps/api/routes/projects.py:12`)
- `GET /projects` (`apps/api/routes/projects.py:27`)
- `GET /projects/{project_id}` (`apps/api/routes/projects.py:32`)
- `PUT /projects/{project_id}` (`apps/api/routes/projects.py:40`)
- `GET /projects/{project_id}/memory/search` (`apps/api/routes/projects.py:48`)
- `GET /projects/{project_id}/runs` (`apps/api/routes/projects.py:56`)

## Runs and Execution

- `POST /projects/{project_id}/runs` (`apps/api/routes/runs.py:465`)
- `POST /runs/{run_id}/plan` (`apps/api/routes/runs.py:778`)
- `POST /runs/{run_id}/start` (`apps/api/routes/runs.py:789`)
- `POST /runs/{run_id}/cancel` (`apps/api/routes/runs.py:803`)
- `POST /runs/{run_id}/pause` (`apps/api/routes/runs.py:814`)
- `POST /runs/{run_id}/resume` (`apps/api/routes/runs.py:824`)
- `POST /runs/{run_id}/tasks/{task_id}/retry` (`apps/api/routes/runs.py:834`)
- `POST /runs/{run_id}/steps/{step_id}/retry` (`apps/api/routes/runs.py:848`)
- `GET /runs/{run_id}` (`apps/api/routes/runs.py:862`)
- `GET /runs/{run_id}/plan` (`apps/api/routes/runs.py:870`)
- `GET /runs/{run_id}/tasks` (`apps/api/routes/runs.py:878`)
- `GET /runs/{run_id}/sources` (`apps/api/routes/runs.py:886`)
- `GET /runs/{run_id}/facts` (`apps/api/routes/runs.py:894`)
- `GET /runs/{run_id}/conflicts` (`apps/api/routes/runs.py:902`)
- `GET /runs/{run_id}/artifacts` (`apps/api/routes/runs.py:910`)
- `GET /runs/{run_id}/snapshot` (`apps/api/routes/runs.py:918`)
- `GET /runs/{run_id}/snapshot/download` (`apps/api/routes/runs.py:923`)
- `GET /runs/{run_id}/approvals` (`apps/api/routes/runs.py:931`)
- `POST /approvals/{approval_id}/approve` (`apps/api/routes/runs.py:939`)
- `POST /approvals/{approval_id}/reject` (`apps/api/routes/runs.py:955`)
- `POST /runs/{run_id}/conflicts/{conflict_id}/resolve` (`apps/api/routes/runs.py:970`)

## Event Stream

- `GET /runs/{run_id}/events` (SSE) (`apps/api/routes/run_events.py:15`)
- `GET /runs/{run_id}/events/download` (NDJSON dump) (`apps/api/routes/run_events.py:53`)

SSE supports `last_event_id` and debug/test mode `once=1` (`apps/api/routes/run_events.py:22`, `apps/api/routes/run_events.py:24`).

## Memory

- `GET /memory/list` (`apps/api/routes/memory.py:20`)
- `POST /memory/create` (`apps/api/routes/memory.py:32`)
- `DELETE /memory/{memory_id}` (`apps/api/routes/memory.py:73`)
- `POST /memory/{memory_id}/pin` (`apps/api/routes/memory.py:87`)
- `POST /memory/{memory_id}/unpin` (`apps/api/routes/memory.py:95`)

## Reminders

- `GET /reminders` (`apps/api/routes/reminders.py:31`)
- `POST /reminders/create` (`apps/api/routes/reminders.py:36`)
- `DELETE /reminders/{reminder_id}` (`apps/api/routes/reminders.py:55`)

## Skills

- `GET /skills` (`apps/api/routes/skills.py:15`)
- `GET /skills/{skill_name}/manifest` (`apps/api/routes/skills.py:21`)
- `POST /skills/reload` (`apps/api/routes/skills.py:30`)

## Artifacts and Secrets

- `GET /artifacts/{artifact_id}/download` (`apps/api/routes/artifacts.py:14`)
- `POST /secrets/unlock` (`apps/api/routes/secrets.py:20`)
- `POST /secrets/openai` (`apps/api/routes/secrets.py:26`)
- `POST /secrets/openai_local` (`apps/api/routes/secrets.py:32`)
- `GET /secrets/openai_local` (`apps/api/routes/secrets.py:39`)
- `GET /secrets/status` (`apps/api/routes/secrets.py:45`)
