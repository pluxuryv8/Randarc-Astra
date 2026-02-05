from __future__ import annotations

from typing import Optional

from memory import store


# EN kept: типы событий — публичный контракт API/клиента
ALLOWED_EVENT_TYPES = {
    "run_created",
    "plan_created",
    "run_started",
    "run_done",
    "run_failed",
    "run_canceled",
    "task_queued",
    "task_started",
    "task_progress",
    "task_failed",
    "task_retried",
    "task_done",
    "source_found",
    "source_fetched",
    "fact_extracted",
    "artifact_created",
    "conflict_detected",
    "verification_done",
    "approval_requested",
    "approval_approved",
    "approval_rejected",
}


def emit(run_id: str, event_type: str, message: str, payload: dict | None = None, level: str = "info", task_id: Optional[str] = None, step_id: Optional[str] = None) -> dict:
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"Неподдерживаемый тип события: {event_type}")
    return store.add_event(
        run_id=run_id,
        event_type=event_type,
        level=level,
        message=message,
        payload=payload or {},
        task_id=task_id,
        step_id=step_id,
    )
