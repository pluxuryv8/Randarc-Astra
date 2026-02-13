from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response, StreamingResponse

from apps.api.auth import require_auth
from memory import store

router = APIRouter(prefix="/api/v1", tags=["events"])


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request):
    require_auth(request)
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")

    last_event_id = request.headers.get("Last-Event-ID") or request.query_params.get("last_event_id")
    # EN kept: параметр once — для тестов/отладки
    once = request.query_params.get("once") in ("1", "true", "yes")
    try:
        last_seq = int(last_event_id) if last_event_id else 0
    except ValueError:
        last_seq = 0

    async def event_generator():
        nonlocal last_seq
        while True:
            if await request.is_disconnected():
                break
            events = store.list_events_since(run_id, last_seq)
            for event in events:
                last_seq = event["seq"]
                data = json.dumps(event, ensure_ascii=False)
                yield f"id: {event['seq']}\n"
                yield f"event: {event['type']}\n"
                yield f"data: {data}\n\n"
            if once:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/runs/{run_id}/events/download")
def download_events(run_id: str, request: Request):
    require_auth(request)
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    events = store.list_events(run_id, limit=5000)
    lines = "\n".join([json.dumps(e, ensure_ascii=False) for e in events])
    return Response(lines, media_type="application/x-ndjson")
