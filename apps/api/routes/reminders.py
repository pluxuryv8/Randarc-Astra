from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException

from apps.api.auth import require_auth
from apps.api.models import ReminderCreateRequest
from core.event_bus import emit
from memory import store

router = APIRouter(prefix="/api/v1/reminders", tags=["reminders"], dependencies=[Depends(require_auth)])


def _default_delivery() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return "telegram"
    return "local"


def _event_run_id(reminder: dict) -> str:
    run_id = reminder.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        return run_id.strip()
    reminder_id = str(reminder.get("id") or "unknown")
    return f"reminder:{reminder_id}"


@router.get("")
def list_reminders(status: str | None = None, limit: int = 200):
    return store.list_reminders(status=status, limit=limit)


@router.post("/create")
def create_reminder(payload: ReminderCreateRequest):
    delivery = payload.delivery or _default_delivery()
    reminder = store.create_reminder(
        payload.due_at,
        payload.text,
        delivery=delivery,
        run_id=payload.run_id,
        source=payload.source,
    )
    emit(
        _event_run_id(reminder),
        "reminder_created",
        "Напоминание создано",
        {"id": reminder["id"], "due_at": reminder["due_at"], "delivery": reminder["delivery"], "run_id": reminder.get("run_id")},
    )
    return reminder


@router.delete("/{reminder_id}")
def cancel_reminder(reminder_id: str):
    reminder = store.cancel_reminder(reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Напоминание не найдено")
    emit(
        _event_run_id(reminder),
        "reminder_cancelled",
        "Напоминание отменено",
        {"id": reminder_id, "run_id": reminder.get("run_id")},
    )
    return reminder
