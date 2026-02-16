from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from apps.api.auth import require_auth
from apps.api.models import MemoryCreateRequest
from core.event_bus import emit
from core.memory_normalize import normalize_memory_texts
from memory import store

router = APIRouter(prefix="/api/v1/memory", tags=["memory"], dependencies=[Depends(require_auth)])

SYSTEM_RUN_ID = "system-memory"


def _event_run_id(run_id: str | None) -> str:
    return run_id or SYSTEM_RUN_ID


@router.get("/list")
def list_memory(query: str = "", tag: str = "", limit: int = Query(50, ge=1, le=200), run_id: str | None = None):
    items = store.list_user_memories(query=query, tag=tag, limit=limit)
    emit(
        _event_run_id(run_id),
        "memory_list_viewed",
        "Просмотр памяти",
        {"query": query, "result_count": len(items)},
    )
    return items


@router.post("/create")
def create_memory(payload: MemoryCreateRequest):
    source = payload.source or "user_command"
    if source not in {"user_command", "imported", "system"}:
        raise HTTPException(status_code=400, detail="Недопустимый источник памяти")

    event_from = payload.from_ or "user_command"
    if event_from not in {"user_command", "ui_button", "system"}:
        event_from = "user_command"

    emit(
        _event_run_id(payload.run_id),
        "memory_save_requested",
        "Запрошено сохранение в память",
        {"from": event_from, "preview_len": len(payload.content or "")},
    )

    content = (payload.content or "").strip()
    items = normalize_memory_texts(content)
    if not items:
        raise HTTPException(status_code=400, detail="Не удалось нормализовать запись памяти")

    try:
        # сохраняем только нормализованные факты
        memory = store.create_user_memory(None, items[0], payload.tags, source=source)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("content_too_long"):
            limit = message.split(":", 1)[-1]
            raise HTTPException(status_code=400, detail=f"Слишком длинный контент (лимит {limit} символов)") from exc
        raise HTTPException(status_code=400, detail="Некорректный контент") from exc

    emit(
        _event_run_id(payload.run_id),
        "memory_saved",
        "Память сохранена",
        {"memory_id": memory["id"], "title": memory["title"], "len": len(memory["content"]), "tags_count": len(memory["tags"] or [])},
    )
    return memory


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, run_id: str | None = None):
    memory = store.delete_user_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Память не найдена")
    emit(
        _event_run_id(run_id),
        "memory_deleted",
        "Запись памяти удалена",
        {"memory_id": memory_id},
    )
    return {"status": "deleted"}


@router.post("/{memory_id}/pin")
def pin_memory(memory_id: str):
    memory = store.set_user_memory_pinned(memory_id, True)
    if not memory:
        raise HTTPException(status_code=404, detail="Память не найдена")
    return memory


@router.post("/{memory_id}/unpin")
def unpin_memory(memory_id: str):
    memory = store.set_user_memory_pinned(memory_id, False)
    if not memory:
        raise HTTPException(status_code=404, detail="Память не найдена")
    return memory
