from __future__ import annotations

import os

from core.event_bus import emit
from core.reminders.parser import parse_reminder_text
from core.skills.result_types import SkillResult
from memory import store


def _default_delivery() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return "telegram"
    return "local"


def run(inputs: dict, ctx) -> SkillResult:
    run_id = ctx.run["id"]
    due_at = inputs.get("due_at") if isinstance(inputs, dict) else None
    reminder_text = inputs.get("text") if isinstance(inputs, dict) else None
    delivery = inputs.get("delivery") if isinstance(inputs, dict) else None

    if not due_at or not reminder_text:
        due_at, reminder_text, _ = parse_reminder_text(ctx.run.get("query_text") or "")

    if not due_at or not reminder_text:
        raise ValueError("reminder_parse_failed")

    delivery = delivery or _default_delivery()

    reminder = store.create_reminder(
        due_at,
        reminder_text,
        delivery=delivery,
        run_id=run_id,
        source="user_command",
    )

    emit(
        run_id,
        "reminder_created",
        "Напоминание создано",
        {"id": reminder["id"], "due_at": reminder["due_at"], "delivery": reminder["delivery"]},
        task_id=ctx.task.get("id"),
        step_id=ctx.plan_step.get("id"),
    )

    return SkillResult(
        what_i_did="Создано напоминание в локальном хранилище.",
        confidence=1.0,
    )
