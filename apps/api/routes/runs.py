from __future__ import annotations

import json
import os
import threading
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from apps.api.auth import require_auth
from apps.api.models import ApprovalDecisionRequest, RunCreate
from core.brain.router import get_brain
from core.brain.types import LLMRequest
from core.event_bus import emit
from core.intent_router import INTENT_ACT, INTENT_ASK, INTENT_CHAT, IntentRouter
from core.llm_routing import ContextItem
from memory import store

router = APIRouter(prefix="/api/v1", tags=["runs"], dependencies=[Depends(require_auth)])


def _get_engine(request: Request):
    engine = request.app.state.engine
    if not engine:
        raise RuntimeError("Движок запусков не инициализирован")
    return engine


def _is_qa_request(request: Request) -> bool:
    header = request.headers.get("X-Astra-QA-Mode", "").strip().lower()
    if header in {"1", "true", "yes", "on"}:
        return True
    return os.getenv("ASTRA_QA_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _build_snapshot(run_id: str) -> dict:
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    plan = store.list_plan_steps(run_id)
    tasks = store.list_tasks(run_id)
    sources = store.list_sources(run_id)
    facts = store.list_facts(run_id)
    conflicts = store.list_conflicts(run_id)
    artifacts = store.list_artifacts(run_id)
    approvals = store.list_approvals(run_id)
    last_events = store.list_events(run_id, limit=200)

    if plan:
        total = len(plan)
        done = len([p for p in plan if p.get("status") == "done"])
    else:
        total = len(tasks)
        done = len([t for t in tasks if t.get("status") == "done"])

    open_conflicts = len([c for c in conflicts if c.get("status") == "open"])

    timestamps = [s.get("retrieved_at") for s in sources if s.get("retrieved_at")]
    timestamps = [t for t in timestamps if t]
    freshness = None
    if timestamps:
        freshness = {
            "min": min(timestamps),
            "max": max(timestamps),
            "count": len(timestamps),
        }

    metrics = {
        "coverage": {"done": done, "total": total},
        "conflicts": open_conflicts,
        "freshness": freshness,
    }

    return {
        "run": run,
        "plan": plan,
        "tasks": tasks,
        "sources": sources,
        "facts": facts,
        "conflicts": conflicts,
        "artifacts": artifacts,
        "approvals": approvals,
        "metrics": metrics,
        "last_events": last_events,
    }


@router.post("/projects/{project_id}/runs")
def create_run(project_id: str, payload: RunCreate, request: Request):
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")

    # EN kept: значения режимов — публичный контракт API/клиента
    allowed_modes = {"plan_only", "research", "execute_confirm", "autopilot_safe"}
    if payload.mode not in allowed_modes:
        raise HTTPException(status_code=400, detail="Недопустимый режим запуска")

    qa_mode = _is_qa_request(request)
    router = IntentRouter(qa_mode=qa_mode)
    decision = router.decide(payload.query_text)

    meta = {
        "intent": decision.intent,
        "intent_confidence": decision.confidence,
        "intent_reasons": decision.reasons,
        "intent_questions": decision.questions,
        "needs_clarification": decision.needs_clarification,
        "qa_mode": qa_mode,
        "act_hint": decision.act_hint.to_dict() if decision.act_hint else None,
        "danger_flags": decision.act_hint.danger_flags if decision.act_hint else [],
        "suggested_run_mode": decision.act_hint.suggested_run_mode if decision.act_hint else None,
        "target": decision.act_hint.target if decision.act_hint else None,
    }

    if decision.intent == INTENT_ACT:
        mode = payload.mode
        suggested_mode = decision.act_hint.suggested_run_mode if decision.act_hint else None
        if suggested_mode == "execute_confirm" and mode != "execute_confirm":
            mode = "execute_confirm"
        if mode not in allowed_modes:
            mode = payload.mode
        run = store.create_run(project_id, payload.query_text, mode, payload.parent_run_id, payload.purpose, meta=meta)
        emit(
            run["id"],
            "run_created",
            "Запуск создан",
            {"project_id": project_id, "mode": mode, "query_text": payload.query_text},
        )
        emit(
            run["id"],
            "intent_decided",
            "Intent decided",
            {
                "intent": decision.intent,
                "confidence": decision.confidence,
                "reasons": decision.reasons,
                "danger_flags": decision.act_hint.danger_flags if decision.act_hint else [],
                "suggested_mode": suggested_mode,
                "selected_mode": mode,
                "target": decision.act_hint.target if decision.act_hint else None,
            },
        )
        engine = _get_engine(request)
        plan_steps = engine.create_plan(run)
        return {"kind": "act", "intent": decision.to_dict(), "run": run, "plan": plan_steps}

    if decision.intent == INTENT_CHAT:
        run = store.create_run(project_id, payload.query_text, "plan_only", payload.parent_run_id, payload.purpose or "chat_only", meta=meta)
        emit(
            run["id"],
            "run_created",
            "Запуск создан",
            {"project_id": project_id, "mode": run["mode"], "query_text": payload.query_text},
        )
        emit(
            run["id"],
            "intent_decided",
            "Intent decided",
            {
                "intent": decision.intent,
                "confidence": decision.confidence,
                "reasons": decision.reasons,
                "danger_flags": [],
                "suggested_mode": run["mode"],
                "target": None,
            },
        )
        brain = get_brain()
        ctx = SimpleNamespace(run=run, task={}, plan_step={}, settings=project.get("settings") or {})
        request = LLMRequest(
            purpose="chat_response",
            task_kind="chat",
            messages=[
                {"role": "system", "content": "Ты ассистент Astra. Отвечай коротко и по делу."},
                {"role": "user", "content": payload.query_text},
            ],
            context_items=[ContextItem(content=payload.query_text, source_type="user_prompt", sensitivity="personal")],
            run_id=run["id"],
        )
        response = brain.call(request, ctx)
        if response.status != "ok":
            raise HTTPException(status_code=502, detail="Не удалось получить ответ LLM")
        emit(
            run["id"],
            "chat_response_generated",
            "Chat response generated",
            {"provider": response.provider, "model_id": response.model_id, "latency_ms": response.latency_ms},
        )
        return {"kind": "chat", "intent": decision.to_dict(), "run": run, "chat_response": response.text}

    if decision.intent == INTENT_ASK:
        run = store.create_run(project_id, payload.query_text, "plan_only", payload.parent_run_id, payload.purpose or "clarify", meta=meta)
        emit(
            run["id"],
            "run_created",
            "Запуск создан",
            {"project_id": project_id, "mode": run["mode"], "query_text": payload.query_text},
        )
        emit(
            run["id"],
            "intent_decided",
            "Intent decided",
            {
                "intent": decision.intent,
                "confidence": decision.confidence,
                "reasons": decision.reasons,
                "danger_flags": [],
                "suggested_mode": run["mode"],
                "target": None,
            },
        )
        emit(
            run["id"],
            "clarify_requested",
            "Clarification requested",
            {"questions": decision.questions},
        )
        return {"kind": "clarify", "intent": decision.to_dict(), "run": run, "questions": decision.questions}

    raise HTTPException(status_code=500, detail="Intent routing failed")


@router.post("/runs/{run_id}/plan")
def create_plan(run_id: str, request: Request):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")

    engine = _get_engine(request)
    steps = engine.create_plan(run)
    return steps


@router.post("/runs/{run_id}/start")
def start_run(run_id: str, request: Request):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")

    engine = _get_engine(request)

    thread = threading.Thread(target=engine.start_run, args=(run_id,), daemon=True)
    thread.start()

    return {"status": "запущено"}


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, request: Request):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")

    engine = _get_engine(request)
    engine.cancel_run(run_id)
    return {"status": "отменено"}


@router.post("/runs/{run_id}/pause")
def pause_run(run_id: str, request: Request):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    engine = _get_engine(request)
    engine.pause_run(run_id)
    return {"status": "пауза"}


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: str, request: Request):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    engine = _get_engine(request)
    engine.resume_run(run_id)
    return {"status": "возобновлено"}


@router.post("/runs/{run_id}/tasks/{task_id}/retry")
def retry_task(run_id: str, task_id: str, request: Request):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    task = store.get_task(task_id)
    if not task or task.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    engine = _get_engine(request)
    thread = threading.Thread(target=engine.retry_task, args=(run_id, task_id), daemon=True)
    thread.start()
    return {"status": "повтор_запущен"}


@router.post("/runs/{run_id}/steps/{step_id}/retry")
def retry_step(run_id: str, step_id: str, request: Request):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    step = store.get_plan_step(step_id)
    if not step or step.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Шаг плана не найден")
    engine = _get_engine(request)
    thread = threading.Thread(target=engine.retry_step, args=(run_id, step_id), daemon=True)
    thread.start()
    return {"status": "повтор_запущен"}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    return run


@router.get("/runs/{run_id}/plan")
def get_plan(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    return store.list_plan_steps(run_id)


@router.get("/runs/{run_id}/tasks")
def get_tasks(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    return store.list_tasks(run_id)


@router.get("/runs/{run_id}/sources")
def get_sources(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    return store.list_sources(run_id)


@router.get("/runs/{run_id}/facts")
def get_facts(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    return store.list_facts(run_id)


@router.get("/runs/{run_id}/conflicts")
def get_conflicts(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    return store.list_conflicts(run_id)


@router.get("/runs/{run_id}/artifacts")
def get_artifacts(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    return store.list_artifacts(run_id)


@router.get("/runs/{run_id}/snapshot")
def get_snapshot(run_id: str):
    return _build_snapshot(run_id)


@router.get("/runs/{run_id}/snapshot/download")
def download_snapshot(run_id: str):
    snapshot = _build_snapshot(run_id)
    payload = json.dumps(snapshot, ensure_ascii=False)
    headers = {"Content-Disposition": f"attachment; filename=снимок_{run_id}.json"}
    return Response(payload, media_type="application/json", headers=headers)


@router.get("/runs/{run_id}/approvals")
def list_approvals(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    return store.list_approvals(run_id)


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, payload: ApprovalDecisionRequest | None = None):
    decision = payload.decision.model_dump(exclude_none=True) if payload and payload.decision else None
    approval = store.update_approval_status(approval_id, "approved", "user", decision=decision)
    if not approval:
        raise HTTPException(status_code=404, detail="Подтверждение не найдено")
    emit(
        approval["run_id"],
        "approval_approved",
        "Подтверждение принято",
        {"approval_id": approval_id, "decision": decision},
        task_id=approval["task_id"],
    )
    return approval


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: str):
    approval = store.update_approval_status(approval_id, "rejected", "user")
    if not approval:
        raise HTTPException(status_code=404, detail="Подтверждение не найдено")
    emit(
        approval["run_id"],
        "approval_rejected",
        "Подтверждение отклонено",
        {"approval_id": approval_id},
        task_id=approval["task_id"],
    )
    return approval


@router.post("/runs/{run_id}/conflicts/{conflict_id}/resolve")
def resolve_conflict(run_id: str, conflict_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    conflict = store.get_conflict(conflict_id)
    if not conflict:
        raise HTTPException(status_code=404, detail="Конфликт не найден")
    query_text = f"Разрешить конфликт по {conflict['fact_key']}"
    sub_run = store.create_run(run["project_id"], query_text, run["mode"], parent_run_id=run_id, purpose="conflict_resolution")
    emit(
        sub_run["id"],
        "run_created",
        "Запуск создан",
        {"project_id": run["project_id"], "mode": sub_run["mode"], "query_text": query_text},
    )
    return sub_run
