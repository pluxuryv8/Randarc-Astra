from __future__ import annotations

import uuid
from pathlib import Path

from core import planner
from core.event_bus import emit
from core.skills.registry import SkillRegistry
from core.skills.runner import SkillRunner
from core.skills.result_types import SkillResult
from memory import store
from memory.db import now_iso


class RunEngine:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.registry = SkillRegistry(base_dir / "skills")
        self.registry.load()
        self.runner = SkillRunner(self.registry, base_dir)

    def create_plan(self, run_id: str, query_text: str) -> list[dict]:
        steps = planner.create_plan_for_query(query_text)
        store.insert_plan_steps(run_id, steps)
        emit(run_id, "plan_created", "План создан", {"steps_count": len(steps)})
        return steps

    def start_run(self, run_id: str) -> None:
        run = store.get_run(run_id)
        if not run:
            raise ValueError("Запуск не найден")

        if run["status"] in ("running", "done", "failed", "canceled", "paused"):
            return

        project = store.get_project(run["project_id"])
        if project:
            run["settings"] = project.get("settings") or {}

        store.update_run_status(run_id, "running", started_at=now_iso())
        emit(run_id, "run_started", "Запуск начат", {"mode": run["mode"]})

        if run["mode"] == "plan_only":
            store.update_run_status(run_id, "done", finished_at=now_iso())
            emit(run_id, "run_done", "Запуск завершён (только план)", {"status": "done"})
            return

        steps = store.list_plan_steps(run_id)
        try:
            for step in steps:
                if store.get_run(run_id)["status"] == "canceled":
                    emit(run_id, "run_canceled", "Запуск отменён", {})
                    return
                self._execute_step(run, step)

            store.update_run_status(run_id, "done", finished_at=now_iso())
            emit(run_id, "run_done", "Запуск завершён", {"status": "done"})
        except Exception as exc:
            store.update_run_status(run_id, "failed", finished_at=now_iso())
            emit(run_id, "run_failed", "Запуск завершён с ошибкой", {"error": str(exc)}, level="error")

    def cancel_run(self, run_id: str) -> None:
        store.update_run_status(run_id, "canceled", finished_at=now_iso())
        emit(run_id, "run_canceled", "Запуск отменён", {})

    def pause_run(self, run_id: str) -> None:
        store.update_run_status(run_id, "paused")
        emit(run_id, "run_paused", "Запуск на паузе", {})

    def resume_run(self, run_id: str) -> None:
        store.update_run_status(run_id, "running")
        emit(run_id, "run_resumed", "Запуск возобновлён", {})

    def retry_task(self, run_id: str, task_id: str) -> dict:
        run = store.get_run(run_id)
        if not run:
            raise ValueError("Запуск не найден")

        task = store.get_task(task_id)
        if not task or task["run_id"] != run_id:
            raise ValueError("Задача не найдена")

        step = store.get_plan_step(task["plan_step_id"])
        if not step:
            raise ValueError("Шаг плана не найден")

        self._ensure_run_running(run, reason="retry_task")
        task_result = self._execute_step(run, step, retry_from_task_id=task_id)
        self._sync_run_status(run_id)
        return task_result

    def retry_step(self, run_id: str, step_id: str) -> dict:
        run = store.get_run(run_id)
        if not run:
            raise ValueError("Запуск не найден")

        step = store.get_plan_step(step_id)
        if not step or step["run_id"] != run_id:
            raise ValueError("Шаг плана не найден")

        previous_task_id = None
        last_task = store.get_last_task_for_step(run_id, step_id)
        if last_task:
            previous_task_id = last_task["id"]

        self._ensure_run_running(run, reason="retry_step")
        task_result = self._execute_step(run, step, retry_from_task_id=previous_task_id)
        self._sync_run_status(run_id)
        return task_result

    def _ensure_run_running(self, run: dict, reason: str) -> None:
        if run["status"] == "canceled":
            raise ValueError("Запуск отменён")
        if run["status"] != "running":
            store.update_run_status(run["id"], "running", started_at=run.get("started_at") or now_iso())
            emit(run["id"], "run_started", "Запуск возобновлён", {"reason": reason})

    def _sync_run_status(self, run_id: str) -> None:
        plan = store.list_plan_steps(run_id)
        if not plan:
            return
        statuses = [p.get("status") for p in plan]
        if all(s == "done" for s in statuses):
            new_status = "done"
        elif any(s == "failed" for s in statuses):
            new_status = "failed"
        else:
            new_status = "running"

        current = store.get_run(run_id)
        current_status = current["status"] if current else None
        if new_status == current_status:
            return
        finished_at = now_iso() if new_status in ("done", "failed") else None
        store.update_run_status(run_id, new_status, finished_at=finished_at)
        if new_status == "done":
            emit(run_id, "run_done", "Запуск завершён", {"status": "done"})
        elif new_status == "failed":
            emit(run_id, "run_failed", "Запуск завершён с ошибкой", {"status": "failed"}, level="error")

    def _execute_step(self, run: dict, step: dict, retry_from_task_id: str | None = None) -> dict:
        run_id = run["id"]
        store.update_plan_step_status(step["id"], "running")

        attempt = store.next_task_attempt(run_id, step["id"])
        task = store.create_task(run_id, step["id"], attempt=attempt)

        if retry_from_task_id:
            emit(
                run_id,
                "task_retried",
                "Повтор задачи",
                {
                    "task_id": task["id"],
                    "step_id": step["id"],
                    "previous_task_id": retry_from_task_id,
                    "attempt": attempt,
                },
                task_id=task["id"],
                step_id=step["id"],
            )

        emit(
            run_id,
            "task_queued",
            "Задача поставлена в очередь",
            {
                "task_id": task["id"],
                "step_id": step["id"],
                "step_index": step["step_index"],
                "skill_name": step["skill_name"],
            },
            task_id=task["id"],
            step_id=step["id"],
        )

        store.update_task_status(task["id"], "running", started_at=now_iso())
        emit(
            run_id,
            "task_started",
            "Задача начата",
            {
                "task_id": task["id"],
                "step_id": step["id"],
                "skill_name": step["skill_name"],
                "started_at": now_iso(),
            },
            task_id=task["id"],
            step_id=step["id"],
        )

        manifest = self.registry.get_manifest(step["skill_name"])
        if not manifest:
            raise RuntimeError(f"Навык не найден: {step['skill_name']}")

        if manifest.scopes in ("confirm_required", "dangerous") and run["mode"] != "execute_confirm":
            store.update_task_status(task["id"], "failed", finished_at=now_iso(), error="требуется_подтверждение")
            store.update_plan_step_status(step["id"], "failed")
            emit(
                run_id,
                "task_failed",
                "Требуется подтверждение",
                {
                    "task_id": task["id"],
                    "step_id": step["id"],
                    "error": "требуется_подтверждение",
                },
                task_id=task["id"],
                step_id=step["id"],
            )
            raise RuntimeError("Требуется режим выполнения с подтверждением")

        try:
            result = self.runner.run_skill(run, step, task)
        except Exception as exc:
            store.update_task_status(task["id"], "failed", finished_at=now_iso(), error=str(exc))
            store.update_plan_step_status(step["id"], "failed")
            emit(
                run_id,
                "task_failed",
                "Задача завершилась с ошибкой",
                {
                    "task_id": task["id"],
                    "step_id": step["id"],
                    "error": str(exc),
                },
                task_id=task["id"],
                step_id=step["id"],
            )
            raise

        self._persist_skill_result(run_id, step, task, result)

        store.update_task_status(task["id"], "done", finished_at=now_iso())
        store.update_plan_step_status(step["id"], "done")
        emit(
            run_id,
            "task_done",
            "Задача завершена",
            {
                "task_id": task["id"],
                "step_id": step["id"],
                "finished_at": now_iso(),
            },
            task_id=task["id"],
            step_id=step["id"],
        )

        return task

    def _persist_skill_result(self, run_id: str, step: dict, task: dict, result: SkillResult) -> None:
        sources_payload = []
        for s in result.sources:
            sid = str(uuid.uuid4())
            payload = {
                "id": sid,
                "url": s.url,
                "title": s.title,
                "domain": s.domain,
                "quality": s.quality,
                "retrieved_at": s.retrieved_at,
                "snippet": s.snippet,
                "pinned": s.pinned,
            }
            sources_payload.append(payload)
            emit(
                run_id,
                "source_found",
                "Источник найден",
                {"source_id": sid, "url": s.url, "title": s.title},
                task_id=task["id"],
                step_id=step["id"],
            )

        if sources_payload:
            store.insert_sources(run_id, sources_payload)
            emit(
                run_id,
                "source_fetched",
                "Источники сохранены",
                {"count": len(sources_payload)},
                task_id=task["id"],
                step_id=step["id"],
            )

        facts_payload = []
        for f in result.facts:
            fid = str(uuid.uuid4())
            payload = {
                "id": fid,
                "key": f.key,
                "value": f.value,
                "confidence": f.confidence,
                "source_ids": f.source_ids,
                "created_at": f.created_at or now_iso(),
            }
            facts_payload.append(payload)
            emit(
                run_id,
                "fact_extracted",
                "Факт извлечён",
                {"fact_id": fid, "key": f.key},
                task_id=task["id"],
                step_id=step["id"],
            )

        if facts_payload:
            store.insert_facts(run_id, facts_payload)

        conflicts = [e for e in result.events if e.get("type") == "conflict"]
        if conflicts:
            conflict_payload = []
            for c in conflicts:
                cid = str(uuid.uuid4())
                payload = {
                    "id": cid,
                    "fact_key": c.get("fact_key"),
                    "group": c.get("group"),
                    "status": "open",
                }
                conflict_payload.append(payload)
                emit(
                    run_id,
                    "conflict_detected",
                    "Обнаружен конфликт",
                    {"conflict_id": cid, "fact_key": c.get("fact_key")},
                    task_id=task["id"],
                    step_id=step["id"],
                )
            store.insert_conflicts(run_id, conflict_payload)

        artifacts_payload = []
        for a in result.artifacts:
            aid = str(uuid.uuid4())
            payload = {
                "id": aid,
                "type": a.type,
                "title": a.title,
                "content_uri": a.content_uri,
                "created_at": a.created_at or now_iso(),
                "meta": a.meta,
            }
            artifacts_payload.append(payload)
            emit(
                run_id,
                "artifact_created",
                "Артефакт создан",
                {"artifact_id": aid, "type": a.type, "title": a.title},
                task_id=task["id"],
                step_id=step["id"],
            )

        if artifacts_payload:
            store.insert_artifacts(run_id, artifacts_payload)

        for evt in result.events:
            if evt.get("type") == "conflict":
                continue
            message = evt.get("message") or "Событие навыка"
            emit(
                run_id,
                "task_progress",
                message,
                {
                    "task_id": task["id"],
                    "step_id": step["id"],
                    "progress": evt.get("progress") or {"current": 0, "total": 1, "unit": "шаг"},
                    "last_message": message,
                },
                task_id=task["id"],
                step_id=step["id"],
            )
