from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.bridge.desktop_bridge import DesktopBridge
from core.event_bus import emit
from core.providers.llm_client import build_llm_client
from core.skills.result_types import ArtifactCandidate, FactCandidate, SkillResult
from memory import store

ALLOWED_ACTIONS = {
    "move_mouse",
    "click",
    "double_click",
    "drag",
    "type",
    "key",
    "scroll",
    "wait",
}

DANGEROUS_KEYWORDS = [
    "оплат",
    "покуп",
    "перевод",
    "подписк",
    "удал",
    "очист",
    "отправ",
    "публикац",
    "создать плейлист",
]


def _artifact_dir(base_dir: str, run_id: str) -> Path:
    path = Path(base_dir) / "artifacts" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_actions(actions: list[dict]) -> str:
    raw = json.dumps(actions, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_prompt(base_dir: str) -> str:
    prompt_path = Path(base_dir) / "prompts" / "autopilot_system.txt"
    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except Exception:
        return "Верни JSON по протоколу автопилота."


@dataclass
class ApprovalContext:
    approval_id: str
    status: str


class AutopilotComputerSkill:
    def __init__(self) -> None:
        self.bridge = DesktopBridge()

    def run(self, inputs: dict, ctx) -> SkillResult:
        goal = inputs.get("goal") or ctx.run.get("query_text") or "Задача"
        max_cycles = int(inputs.get("max_cycles") or 30)
        max_actions = int(inputs.get("max_actions") or 6)
        screenshot_width = int(inputs.get("screenshot_width") or 1280)
        quality = int(inputs.get("quality") or 60)
        hints = inputs.get("hints") or []

        if ctx.run.get("mode") not in ("execute_confirm", "autopilot_safe"):
            raise RuntimeError("Для автопилота нужен режим выполнения с подтверждением")

        try:
            client = build_llm_client(ctx.settings)
        except Exception as exc:
            raise RuntimeError(f"Не настроена языковая модель: {exc}")

        cycles_log: list[dict] = []
        interventions: list[str] = []
        last_action_hashes: list[str] = []
        done = False

        for cycle in range(1, max_cycles + 1):
            run = store.get_run(ctx.run["id"])
            if not run:
                break
            if run.get("status") == "canceled":
                interventions.append("Запуск отменён пользователем")
                break
            if run.get("status") == "paused":
                emit(ctx.run["id"], "autopilot_state", "Пауза автопилота", {
                    "goal": goal,
                    "plan": [],
                    "step_summary": "Пауза",
                    "reason": "Ожидание возобновления",
                    "actions": [],
                    "status": "paused",
                    "cycle": cycle,
                    "max_cycles": max_cycles,
                    "needs_user": False,
                    "ask_confirm": {"required": False, "reason": "", "proposed_effect": ""},
                })
                time.sleep(0.5)
                continue

            screen = self.bridge.autopilot_capture(max_width=screenshot_width, quality=quality)
            image_b64 = screen.get("image_base64") or ""
            image_bytes = base64.b64decode(image_b64) if image_b64 else b""
            screen_hash = _hash_bytes(image_bytes) if image_bytes else ""
            image_width = int(screen.get("width") or 0)
            image_height = int(screen.get("height") or 0)

            model_input = {
                "goal": goal,
                "hints": hints,
                "cycle": cycle,
                "max_cycles": max_cycles,
                "screen": {
                    "image_base64": image_b64,
                    "width": screen.get("width"),
                    "height": screen.get("height"),
                },
                "recent_actions": cycles_log[-3:],
            }

            response = client.chat(
                [
                    {"role": "system", "content": _load_prompt(ctx.base_dir)},
                    {"role": "user", "content": json.dumps(model_input, ensure_ascii=False)},
                ],
                temperature=0.2,
            )

            content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}").strip()
            try:
                parsed = json.loads(content)
            except Exception:
                emit(ctx.run["id"], "task_progress", "Ответ модели не разобран", {
                    "task_id": ctx.task["id"],
                    "step_id": ctx.plan_step["id"],
                    "progress": {"current": cycle, "total": max_cycles, "unit": "цикл"},
                    "last_message": "Не удалось разобрать ответ модели",
                }, task_id=ctx.task["id"], step_id=ctx.plan_step["id"])
                interventions.append("Неверный формат ответа модели")
                break

            actions = [a for a in parsed.get("actions", []) if a.get("type") in ALLOWED_ACTIONS]
            actions = actions[:max_actions]
            action_hash = _hash_actions(actions)
            last_action_hashes.append(action_hash)
            if len(last_action_hashes) > 3:
                last_action_hashes.pop(0)
            if len(set(last_action_hashes)) == 1 and len(last_action_hashes) == 3:
                interventions.append("Обнаружено зацикливание действий")
                emit(ctx.run["id"], "autopilot_state", "Обнаружено зацикливание", {
                    "goal": parsed.get("goal", goal),
                    "plan": parsed.get("plan", []),
                    "step_summary": parsed.get("step_summary", ""),
                    "reason": "Действия повторяются без прогресса",
                    "actions": actions,
                    "status": "needs_user",
                    "cycle": cycle,
                    "max_cycles": max_cycles,
                    "screen_hash": screen_hash,
                    "action_hash": action_hash,
                    "needs_user": True,
                    "ask_confirm": parsed.get("ask_confirm", {}),
                })
                break

            needs_user = bool(parsed.get("needs_user"))
            ask_confirm = parsed.get("ask_confirm") or {"required": False, "reason": "", "proposed_effect": ""}
            ask_confirm_required = bool(ask_confirm.get("required")) or _goal_requires_confirm(goal)

            status = "running"
            if needs_user:
                status = "needs_user"
                interventions.append(parsed.get("reason") or "Требуется ручное действие")

            emit(ctx.run["id"], "autopilot_state", "Состояние автопилота", {
                "goal": parsed.get("goal", goal),
                "plan": parsed.get("plan", []),
                "step_summary": parsed.get("step_summary", ""),
                "reason": parsed.get("reason", ""),
                "actions": actions,
                "status": status,
                "cycle": cycle,
                "max_cycles": max_cycles,
                "screen_hash": screen_hash,
                "action_hash": action_hash,
                "needs_user": needs_user,
                "ask_confirm": ask_confirm,
            })

            emit(ctx.run["id"], "task_progress", "Цикл автопилота", {
                "task_id": ctx.task["id"],
                "step_id": ctx.plan_step["id"],
                "progress": {"current": cycle, "total": max_cycles, "unit": "цикл"},
                "last_message": parsed.get("step_summary", ""),
            }, task_id=ctx.task["id"], step_id=ctx.plan_step["id"])

            cycles_log.append({
                "cycle": cycle,
                "goal": parsed.get("goal", goal),
                "step_summary": parsed.get("step_summary", ""),
                "reason": parsed.get("reason", ""),
                "actions": actions,
                "needs_user": needs_user,
                "ask_confirm": ask_confirm,
                "screen_hash": screen_hash,
                "action_hash": action_hash,
            })

            if parsed.get("done"):
                done = True
                break

            if needs_user:
                break

            if ask_confirm_required:
                approval = self._request_confirm(ctx, goal, ask_confirm, actions)
                if approval.status != "approved":
                    interventions.append("Пользователь отклонил подтверждение")
                    break

            self._execute_actions(actions, ctx, image_width, image_height)
            time.sleep(0.2)

        out_dir = _artifact_dir(ctx.base_dir, ctx.run["id"])
        log_path = out_dir / "autopilot_log.json"
        _write_json(log_path, {
            "goal": goal,
            "done": done,
            "cycles": cycles_log,
            "interventions": interventions,
        })

        summary_path = out_dir / "autopilot_summary.md"
        summary_text = _render_summary(goal, done, cycles_log, interventions)
        summary_path.write_text(summary_text, encoding="utf-8")

        artifacts = [
            ArtifactCandidate(
                type="autopilot_log_json",
                title="Лог автопилота",
                content_uri=str(log_path),
                meta={"cycles": len(cycles_log)},
            ),
            ArtifactCandidate(
                type="autopilot_summary_md",
                title="Итог автопилота",
                content_uri=str(summary_path),
                meta={"done": done},
            ),
        ]

        facts = [FactCandidate(key="Автопилот завершён", value={"done": done, "cycles": len(cycles_log)}, confidence=0.6)]

        return SkillResult(
            what_i_did="Выполнен автопилотный цикл управления компьютером.",
            artifacts=artifacts,
            facts=facts,
            confidence=0.6 if done else 0.3,
            assumptions=interventions,
        )

    def _execute_actions(self, actions: list[dict], ctx, image_width: int, image_height: int) -> None:
        for action in actions:
            action_type = action.get("type")
            if action_type == "wait":
                time.sleep(float(action.get("ms") or 500) / 1000)
                continue
            self.bridge.autopilot_act(action, image_width=image_width, image_height=image_height)

    def _request_confirm(self, ctx, goal: str, ask_confirm: dict, actions: list[dict]) -> ApprovalContext:
        title = ask_confirm.get("reason") or "Подтвердите действие"
        description = ask_confirm.get("proposed_effect") or goal
        approval = store.create_approval(
            run_id=ctx.run["id"],
            task_id=ctx.task["id"],
            scope="autopilot",
            title=title,
            description=description,
            proposed_actions=actions,
        )
        emit(ctx.run["id"], "approval_requested", "Запрошено подтверждение", {
            "approval_id": approval["id"],
            "scope": approval["scope"],
            "title": approval["title"],
            "description": approval["description"],
            "proposed_actions": approval["proposed_actions"],
        }, task_id=ctx.task["id"], step_id=ctx.plan_step["id"])

        store.update_task_status(ctx.task["id"], "waiting_approval")
        emit(ctx.run["id"], "task_progress", "Ожидание подтверждения", {
            "task_id": ctx.task["id"],
            "step_id": ctx.plan_step["id"],
            "progress": {"current": 0, "total": 1, "unit": "подтверждение"},
            "last_message": "Ожидание подтверждения",
        }, task_id=ctx.task["id"], step_id=ctx.plan_step["id"])

        approval = self._wait_for_approval(approval["id"], ctx.run["id"])
        if approval and approval.get("status") == "approved":
            emit(ctx.run["id"], "approval_approved", "Подтверждение принято", {"approval_id": approval["id"]}, task_id=ctx.task["id"], step_id=ctx.plan_step["id"])
            store.update_task_status(ctx.task["id"], "running")
            return ApprovalContext(approval_id=approval["id"], status="approved")

        emit(ctx.run["id"], "approval_rejected", "Подтверждение отклонено", {"approval_id": approval["id"]}, task_id=ctx.task["id"], step_id=ctx.plan_step["id"])
        return ApprovalContext(approval_id=approval["id"], status="rejected")

    def _wait_for_approval(self, approval_id: str, run_id: str) -> dict | None:
        while True:
            approval = store.get_approval(approval_id)
            if not approval:
                return None
            if approval["status"] in ("approved", "rejected", "expired"):
                return approval
            run = store.get_run(run_id)
            if run and run["status"] == "canceled":
                store.update_approval_status(approval_id, "expired", "system")
                return None
            time.sleep(0.5)


def _goal_requires_confirm(goal: str) -> bool:
    lower = goal.lower()
    return any(word in lower for word in DANGEROUS_KEYWORDS)


def _render_summary(goal: str, done: bool, cycles_log: list[dict], interventions: list[str]) -> str:
    lines = ["# Итог автопилота", "", f"Цель: {goal}", "", f"Статус: {'выполнено' if done else 'не завершено'}", ""]
    lines.append("## Что было сделано")
    for entry in cycles_log:
        summary = entry.get("step_summary") or ""
        if summary:
            lines.append(f"- {summary}")
    if not cycles_log:
        lines.append("- Действий не было")
    lines.append("")
    lines.append("## Вмешательства")
    if interventions:
        for item in interventions:
            lines.append(f"- {item}")
    else:
        lines.append("- Не потребовались")
    lines.append("")
    return "\n".join(lines)


skill = AutopilotComputerSkill()
