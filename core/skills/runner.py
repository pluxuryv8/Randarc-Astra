from __future__ import annotations

import time
from pathlib import Path

from core.event_bus import emit
from core.safety.approvals import (
    approval_type_from_flags,
    build_preview_for_step,
    preview_summary,
    proposed_actions_from_preview,
)
from core.skill_context import SkillContext
from core.skills.registry import SkillRegistry
from core.skills.result_types import SkillResult
from core.skills.schemas import load_schema, validate_inputs
from memory import store


class SkillRunner:
    def __init__(self, registry: SkillRegistry, base_dir: Path):
        self.registry = registry
        self.base_dir = base_dir

    def run_skill(self, run: dict, step: dict, task: dict) -> SkillResult:
        manifest = self.registry.get_manifest(step["skill_name"])
        if not manifest:
            raise RuntimeError(f"Навык не найден: {step['skill_name']}")

        inputs = step.get("inputs") or {}
        schema = load_schema(manifest.inputs_schema, self.base_dir)
        validate_inputs(schema, inputs)

        skill_module = self.registry.get_skill(step["skill_name"])
        skill_obj = getattr(skill_module, "skill", None)

        ctx = SkillContext(run=run, plan_step=step, task=task, settings=run.get("settings") or {}, base_dir=str(self.base_dir))

        if manifest.scopes in ("confirm_required", "dangerous"):
            approval_payload = None
            if skill_obj and hasattr(skill_obj, "build_approval"):
                approval_payload = skill_obj.build_approval(inputs, ctx)
            elif hasattr(skill_module, "build_approval"):
                approval_payload = skill_module.build_approval(inputs, ctx)

            approval_type = approval_type_from_flags(step.get("danger_flags") or [])
            preview = build_preview_for_step(run, step, approval_type)

            if not approval_payload:
                approval_payload = {
                    "scope": manifest.name,
                    "title": preview.get("summary") or f"Подтверждение: {manifest.name}",
                    "description": preview.get("risk") or "Требуется подтверждение",
                    "proposed_actions": proposed_actions_from_preview(approval_type, preview),
                    "approval_type": approval_type,
                    "preview": preview,
                }

            approval = store.create_approval(
                run_id=run["id"],
                task_id=task["id"],
                step_id=step.get("id"),
                scope=approval_payload.get("scope") or manifest.name,
                approval_type=approval_payload.get("approval_type") or approval_type,
                title=approval_payload.get("title") or "Требуется подтверждение",
                description=approval_payload.get("description") or "",
                proposed_actions=approval_payload.get("proposed_actions") or [],
                preview=approval_payload.get("preview") or preview,
            )

            emit(
                run["id"],
                "approval_requested",
                "Запрошено подтверждение",
                {
                    "approval_id": approval["id"],
                    "approval_type": approval.get("approval_type"),
                    "step_id": step.get("id"),
                    "preview_summary": preview_summary(approval_payload.get("preview") or preview),
                    "scope": approval["scope"],
                    "title": approval["title"],
                    "description": approval["description"],
                    "proposed_actions": approval["proposed_actions"],
                },
                task_id=task["id"],
                step_id=step["id"],
            )

            store.update_task_status(task["id"], "waiting_approval")
            emit(
                run["id"],
                "task_progress",
                "Ожидание подтверждения",
                {
                    "task_id": task["id"],
                    "step_id": step["id"],
                    "progress": {"current": 0, "total": 1, "unit": "подтверждение"},
                    "last_message": "Запрошено подтверждение",
                },
                task_id=task["id"],
                step_id=step["id"],
            )

            approval = self._wait_for_approval(run["id"], approval["id"])
            emit(
                run["id"],
                "approval_resolved",
                "Подтверждение завершено",
                {
                    "approval_id": approval["id"],
                    "status": approval["status"],
                    "decision": approval.get("decision"),
                    "approval_type": approval.get("approval_type"),
                    "step_id": step.get("id"),
                },
                task_id=task["id"],
                step_id=step["id"],
            )
            if approval["status"] != "approved":
                emit(
                    run["id"],
                    "approval_rejected",
                    "Подтверждение отклонено",
                    {"approval_id": approval["id"]},
                    task_id=task["id"],
                    step_id=step["id"],
                )
                emit(
                    run["id"],
                    "step_cancelled_by_user",
                    "Шаг отменён пользователем",
                    {"step_id": step.get("id"), "approval_id": approval["id"]},
                    task_id=task["id"],
                    step_id=step["id"],
                )
                raise RuntimeError("Подтверждение отклонено")

            emit(
                run["id"],
                "approval_approved",
                "Подтверждение принято",
                {"approval_id": approval["id"]},
                task_id=task["id"],
                step_id=step["id"],
            )
            store.update_task_status(task["id"], "running")

        if skill_obj and hasattr(skill_obj, "execute"):
            return skill_obj.execute(inputs, ctx)
        if hasattr(skill_module, "run"):
            return skill_module.run(inputs, ctx)
        raise RuntimeError(f"Отсутствует точка входа навыка: {step['skill_name']}")

    def _wait_for_approval(self, run_id: str, approval_id: str) -> dict:
        while True:
            approval = store.get_approval(approval_id)
            if not approval:
                raise RuntimeError("Подтверждение не найдено")
            if approval["status"] in ("approved", "rejected", "expired"):
                return approval
            run = store.get_run(run_id)
            if run and run["status"] == "canceled":
                approval = store.update_approval_status(approval_id, "expired", "system")
                return approval
            time.sleep(0.5)
