from __future__ import annotations

from pathlib import Path
from typing import Optional

from memory import store

_DEFAULT_EVENT_TYPES = {
    "run_created",
    "plan_created",
    "run_started",
    "run_done",
    "run_failed",
    "run_canceled",
    "run_paused",
    "run_resumed",
    "task_queued",
    "task_started",
    "task_progress",
    "task_failed",
    "task_retried",
    "task_done",
    "step_planned",
    "source_found",
    "source_fetched",
    "fact_extracted",
    "artifact_created",
    "conflict_detected",
    "verification_done",
    "approval_requested",
    "approval_resolved",
    "approval_approved",
    "approval_rejected",
    "llm_route_decided",
    "llm_request_sanitized",
    "llm_request_started",
    "llm_request_succeeded",
    "llm_request_failed",
    "llm_budget_exceeded",
    "autopilot_state",
    "autopilot_action",
    "intent_decided",
    "clarify_requested",
    "chat_response_generated",
}


def _load_event_types_from_schemas() -> set[str]:
    events_dir = Path(__file__).resolve().parents[1] / "schemas" / "events"
    if not events_dir.exists():
        return set()
    types: set[str] = set()
    for path in events_dir.glob("*.schema.json"):
        name = path.name
        if name.endswith(".schema.json"):
            types.add(name[: -len(".schema.json")])
    return types


# EN kept: типы событий — публичный контракт API/клиента
ALLOWED_EVENT_TYPES = _load_event_types_from_schemas() or _DEFAULT_EVENT_TYPES


def get_allowed_event_types() -> set[str]:
    return set(ALLOWED_EVENT_TYPES)


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
