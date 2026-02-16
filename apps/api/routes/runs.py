from __future__ import annotations

import json
import os
import threading
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from apps.api.auth import require_auth
from apps.api.models import ApprovalDecisionRequest, RunCreate
from core.brain.router import get_brain
from core.brain.types import LLMRequest
from core.chat_context import (
    build_chat_messages,
    build_user_profile_context,
)
from core.event_bus import emit
from core.intent_router import INTENT_ACT, INTENT_ASK, INTENT_CHAT, IntentDecision, IntentRouter
from core.llm_routing import ContextItem
from core.memory.interpreter import MemoryInterpretationError, interpret_user_message_for_memory
from core.semantic.decision import SemanticDecisionError
from memory import store
from skills.memory_save import skill as memory_save_skill

router = APIRouter(prefix="/api/v1", tags=["runs"], dependencies=[Depends(require_auth)])

CHAT_HISTORY_TURNS = 20


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


def _intent_summary(decision) -> str:
    parts = [f"intent={decision.intent}"]
    if decision.plan_hint:
        parts.append(f"plan_hint={','.join(decision.plan_hint)}")
    if decision.memory_item:
        parts.append("memory_item=1")
    return "; ".join(parts)


def _emit_intent_decided(run_id: str, decision, selected_mode: str | None) -> None:
    emit(
        run_id,
        "intent_decided",
        "Интент определён",
        {
            "intent": decision.intent,
            "confidence": decision.confidence,
            "reasons": decision.reasons,
            "danger_flags": decision.act_hint.danger_flags if decision.act_hint else [],
            "suggested_mode": decision.act_hint.suggested_run_mode if decision.act_hint else selected_mode,
            "selected_mode": selected_mode,
            "target": decision.act_hint.target if decision.act_hint else None,
            "decision_path": decision.decision_path,
            "summary": _intent_summary(decision),
        },
    )


def _semantic_resilience_decision(error_code: str) -> IntentDecision:
    # Semantic classification is infra and can fail independently from chat generation.
    # We degrade to CHAT to preserve a useful user response instead of returning 502.
    return IntentDecision(
        intent=INTENT_CHAT,
        confidence=0.0,
        reasons=["semantic_resilience", error_code],
        questions=[],
        needs_clarification=False,
        act_hint=None,
        plan_hint=["CHAT_RESPONSE"],
        memory_item=None,
        response_style_hint=None,
        user_visible_note="Семантическая классификация недоступна, отвечаю напрямую.",
        decision_path="semantic_resilience",
    )


def _chat_resilience_text(error_type: str | None) -> str:
    if error_type == "budget_exceeded":
        return "Лимит обращений к модели исчерпан для этого запуска. Попробуй ещё раз чуть позже."
    if error_type == "missing_api_key":
        return "Облачная модель недоступна: не задан OPENAI_API_KEY."
    if error_type and "llm_call_failed" in error_type:
        return "Локальная модель сейчас недоступна. Проверь Ollama и выбранную модель, затем повтори запрос."
    if error_type in {"model_not_found", "http_error", "connection_error", "invalid_json"}:
        return "Локальная модель сейчас недоступна. Проверь Ollama и выбранную модель, затем повтори запрос."
    return "Не удалось получить ответ модели. Повтори запрос."


def _save_memory_payload(run: dict, payload: dict[str, Any] | None, settings: dict[str, Any]) -> None:
    if not payload:
        return
    ctx = SimpleNamespace(run=run, task={}, plan_step={}, settings=settings)
    memory_save_skill.run(payload, ctx)


def _style_hint_from_interpretation(memory_interpretation: dict[str, Any] | None) -> str | None:
    if not isinstance(memory_interpretation, dict):
        return None
    preferences = memory_interpretation.get("preferences")
    if not isinstance(preferences, list):
        return None
    hints: list[str] = []
    for item in preferences:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        key = key.strip().lower()
        value = value.strip()
        if not value:
            continue
        if key == "style.brevity" and value.lower() in {"short", "brief", "compact"}:
            hints.append("Отвечай коротко и по делу.")
        elif key == "style.tone":
            hints.append(f"Тон ответа: {value}.")
        elif key == "user.addressing.preference":
            hints.append(f"Формат обращения к пользователю: {value}.")
        elif key == "response.format":
            hints.append(f"Формат ответа: {value}.")
    unique = []
    for hint in hints:
        if hint not in unique:
            unique.append(hint)
    if not unique:
        return None
    return " ".join(unique[:3])


def _name_from_interpretation(memory_interpretation: dict[str, Any] | None) -> str | None:
    if not isinstance(memory_interpretation, dict):
        return None
    facts = memory_interpretation.get("facts")
    if not isinstance(facts, list):
        return None
    for item in facts:
        if not isinstance(item, dict):
            continue
        if item.get("key") != "user.name":
            continue
        value = item.get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _memory_payload_from_interpretation(query_text: str, memory_interpretation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(memory_interpretation, dict):
        return None
    if memory_interpretation.get("should_store") is not True:
        return None
    summary = memory_interpretation.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    title = memory_interpretation.get("title") if isinstance(memory_interpretation.get("title"), str) else "Профиль пользователя"
    return {
        "content": query_text.strip(),
        "origin": "auto",
        "memory_payload": {
            "title": title.strip() or "Профиль пользователя",
            "summary": summary.strip(),
            "confidence": memory_interpretation.get("confidence"),
            "facts": memory_interpretation.get("facts") if isinstance(memory_interpretation.get("facts"), list) else [],
            "preferences": memory_interpretation.get("preferences")
            if isinstance(memory_interpretation.get("preferences"), list)
            else [],
            "possible_facts": memory_interpretation.get("possible_facts")
            if isinstance(memory_interpretation.get("possible_facts"), list)
            else [],
        },
    }


def _known_profile_payload(memories: list[dict]) -> dict[str, Any]:
    trimmed: list[dict[str, Any]] = []
    for item in memories[:20]:
        if not isinstance(item, dict):
            continue
        trimmed.append(
            {
                "title": item.get("title"),
                "content": item.get("content"),
                "meta": item.get("meta") if isinstance(item.get("meta"), dict) else {},
            }
        )
    return {"memories": trimmed}


def _build_chat_system_prompt(memories: list[dict], response_style_hint: str | None) -> str:
    profile_context = build_user_profile_context(memories)
    profile_block = profile_context.get("profile_block")
    style_hints = profile_context.get("style_hints") if isinstance(profile_context.get("style_hints"), list) else []
    user_name = profile_context.get("user_name") if isinstance(profile_context.get("user_name"), str) else None

    base = (
        "Ты ассистент Astra. "
        "Всегда отвечай на русском, спокойно и уважительно. "
        "Избегай канцелярита и длинных формальных оборотов. "
        "Если пользователь спрашивает, как его зовут или что ты помнишь о нём, "
        "отвечай строго по блоку профиля ниже. "
        "Если профиль пуст, честно скажи, что пока не знаешь."
    )
    if user_name:
        base = f"{base} Имя пользователя: {user_name}. Можно обращаться по имени, но не в каждом предложении."
    if response_style_hint:
        base = f"{base} Текущая стилевая подсказка: {response_style_hint}"
    if style_hints:
        base = f"{base} Стиль из профиля: {' '.join(style_hints[:3])}"
    if profile_block:
        return f"{base}\n\nПрофиль пользователя:\n{profile_block}"
    return f"{base}\n\nПрофиль пользователя: пусто."


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
    run = store.create_run(
        project_id,
        payload.query_text,
        payload.mode,
        payload.parent_run_id,
        payload.purpose,
        meta={"intent": INTENT_ASK, "qa_mode": qa_mode, "intent_path": "pending"},
    )
    emit(
        run["id"],
        "run_created",
        "Запуск создан",
        {"project_id": project_id, "mode": run["mode"], "query_text": payload.query_text},
    )

    router = IntentRouter(qa_mode=qa_mode)
    settings = project.get("settings") or {}
    semantic_error_code: str | None = None
    try:
        decision = router.decide(payload.query_text, run_id=run["id"], settings=settings)
    except SemanticDecisionError as exc:
        semantic_error_code = exc.code
        emit(
            run["id"],
            "llm_request_failed",
            "Semantic decision failed",
            {
                "provider": "local",
                "model_id": None,
                "error_type": exc.code,
                "http_status_if_any": None,
                "retry_count": 0,
            },
        )
        decision = _semantic_resilience_decision(exc.code)
    except Exception:  # noqa: BLE001
        semantic_error_code = "semantic_decision_unhandled_error"
        emit(
            run["id"],
            "llm_request_failed",
            "Semantic decision failed",
            {
                "provider": "local",
                "model_id": None,
                "error_type": "semantic_decision_unhandled_error",
                "http_status_if_any": None,
                "retry_count": 0,
            },
        )
        decision = _semantic_resilience_decision(semantic_error_code)

    semantic_resilience = decision.decision_path == "semantic_resilience"
    profile_memories = store.list_user_memories(limit=50)
    profile_context = build_user_profile_context(profile_memories)
    history = store.list_recent_chat_turns(run.get("parent_run_id"), limit_turns=12)
    memory_interpretation: dict[str, Any] | None = None
    memory_interpretation_error: str | None = None
    if semantic_resilience:
        memory_interpretation_error = "memory_interpreter_skipped_semantic_resilience"
    else:
        try:
            memory_interpretation = interpret_user_message_for_memory(
                payload.query_text,
                history,
                _known_profile_payload(profile_memories),
                brain=get_brain(),
                run_id=run["id"],
                settings=settings,
            )
        except MemoryInterpretationError as exc:
            memory_interpretation_error = exc.code
            emit(
                run["id"],
                "llm_request_failed",
                "Memory interpretation failed",
                {
                    "provider": "local",
                    "model_id": None,
                    "error_type": exc.code,
                    "http_status_if_any": None,
                    "retry_count": 0,
                },
            )
        except Exception:  # noqa: BLE001
            memory_interpretation_error = "memory_interpreter_unhandled_error"
            emit(
                run["id"],
                "llm_request_failed",
                "Memory interpretation failed",
                {
                    "provider": "local",
                    "model_id": None,
                    "error_type": "memory_interpreter_unhandled_error",
                    "http_status_if_any": None,
                    "retry_count": 0,
                },
            )

    interpreted_style_hint = _style_hint_from_interpretation(memory_interpretation)
    profile_style_hints = profile_context.get("style_hints") if isinstance(profile_context.get("style_hints"), list) else []
    profile_style_hint = " ".join(profile_style_hints[:3]) if profile_style_hints else None
    effective_response_style_hint = decision.response_style_hint or interpreted_style_hint or profile_style_hint
    interpreted_user_name = _name_from_interpretation(memory_interpretation)
    if not interpreted_user_name:
        profile_name = profile_context.get("user_name")
        if isinstance(profile_name, str) and profile_name.strip():
            interpreted_user_name = profile_name.strip()
    memory_payload = _memory_payload_from_interpretation(payload.query_text, memory_interpretation)

    selected_mode = "plan_only"
    selected_purpose = payload.purpose
    if decision.intent == INTENT_ACT:
        selected_mode = payload.mode
        if decision.act_hint and decision.act_hint.suggested_run_mode == "execute_confirm":
            selected_mode = "execute_confirm"
        if selected_mode not in allowed_modes:
            selected_mode = payload.mode
    elif decision.intent == INTENT_CHAT:
        selected_mode = "plan_only"
        selected_purpose = payload.purpose or "chat_only"
    elif decision.intent == INTENT_ASK:
        selected_mode = "plan_only"
        selected_purpose = payload.purpose or "clarify"

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
        "intent_path": decision.decision_path,
        "plan_hint": decision.plan_hint,
        "memory_item": decision.memory_item,
        "memory_interpretation": memory_interpretation,
        "memory_interpretation_error": memory_interpretation_error,
        "response_style_hint": effective_response_style_hint,
        "user_visible_note": decision.user_visible_note,
        "user_name": interpreted_user_name,
        "semantic_error_code": semantic_error_code,
    }
    updated = store.update_run_meta_and_mode(
        run["id"],
        mode=selected_mode,
        purpose=selected_purpose,
        meta=meta,
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Не удалось обновить запуск после semantic decision")
    run = updated

    _emit_intent_decided(run["id"], decision, selected_mode)

    if decision.intent in {INTENT_CHAT, INTENT_ASK}:
        try:
            _save_memory_payload(run, memory_payload, settings)
        except Exception as exc:  # noqa: BLE001
            store.update_run_status(run["id"], "failed")
            emit(run["id"], "run_failed", "Запуск завершён с ошибкой", {"error": "memory_save_failed"}, level="error")
            raise HTTPException(status_code=500, detail=f"memory_save_failed:{exc}") from exc

    if decision.intent == INTENT_ACT:
        try:
            engine = _get_engine(request)
            plan_steps = engine.create_plan(run)
        except Exception as exc:  # noqa: BLE001
            store.update_run_status(run["id"], "failed")
            emit(run["id"], "run_failed", "Запуск завершён с ошибкой", {"error": str(exc)}, level="error")
            raise
        return {"kind": "act", "intent": decision.to_dict(), "run": run, "plan": plan_steps}

    if decision.intent == INTENT_CHAT:
        if semantic_resilience:
            fallback_error = semantic_error_code or "semantic_resilience"
            fallback_text = _chat_resilience_text(fallback_error)
            emit(
                run["id"],
                "chat_response_generated",
                "Ответ сформирован (degraded)",
                {
                    "provider": "local",
                    "model_id": None,
                    "latency_ms": None,
                    "text": fallback_text,
                    "degraded": True,
                    "error_type": fallback_error,
                    "http_status_if_any": None,
                },
            )
            return {"kind": "chat", "intent": decision.to_dict(), "run": run, "chat_response": fallback_text}

        brain = get_brain()
        ctx = SimpleNamespace(run=run, task={}, plan_step={}, settings=settings)
        memories = store.list_user_memories(limit=50)
        system_text = _build_chat_system_prompt(memories, effective_response_style_hint)
        history = store.list_recent_chat_turns(run.get("parent_run_id"), limit_turns=CHAT_HISTORY_TURNS)
        llm_request = LLMRequest(
            purpose="chat_response",
            task_kind="chat",
            messages=build_chat_messages(system_text, history, payload.query_text),
            context_items=[ContextItem(content=payload.query_text, source_type="user_prompt", sensitivity="personal")],
            run_id=run["id"],
        )
        fallback_text: str | None = None
        fallback_provider = "local"
        fallback_model_id = None
        fallback_latency_ms = None
        fallback_error_type: str | None = None
        fallback_http_status: int | None = None
        try:
            response = brain.call(llm_request, ctx)
        except Exception as exc:  # noqa: BLE001
            fallback_error_type = str(getattr(exc, "error_type", "chat_llm_unhandled_error"))
            fallback_http_status = getattr(exc, "status_code", None)
            fallback_provider = str(getattr(exc, "provider", "local") or "local")
            fallback_model_id = getattr(exc, "model_id", None)
            fallback_text = _chat_resilience_text(fallback_error_type)
            if fallback_error_type == "chat_llm_unhandled_error":
                emit(
                    run["id"],
                    "llm_request_failed",
                    "Chat LLM failed",
                    {
                        "provider": fallback_provider,
                        "model_id": fallback_model_id,
                        "error_type": fallback_error_type,
                        "http_status_if_any": fallback_http_status,
                        "retry_count": 0,
                    },
                )
        else:
            if response.status != "ok":
                fallback_error_type = response.error_type or "chat_llm_failed"
                fallback_provider = response.provider or "local"
                fallback_model_id = response.model_id
                fallback_latency_ms = response.latency_ms
                fallback_text = _chat_resilience_text(fallback_error_type)

        if fallback_text is not None:
            emit(
                run["id"],
                "chat_response_generated",
                "Ответ сформирован (degraded)",
                {
                    "provider": fallback_provider,
                    "model_id": fallback_model_id,
                    "latency_ms": fallback_latency_ms,
                    "text": fallback_text,
                    "degraded": True,
                    "error_type": fallback_error_type,
                    "http_status_if_any": fallback_http_status,
                },
            )
            return {"kind": "chat", "intent": decision.to_dict(), "run": run, "chat_response": fallback_text}

        emit(
            run["id"],
            "chat_response_generated",
            "Ответ сформирован",
            {
                "provider": response.provider,
                "model_id": response.model_id,
                "latency_ms": response.latency_ms,
                "text": response.text,
            },
        )
        return {"kind": "chat", "intent": decision.to_dict(), "run": run, "chat_response": response.text}

    if decision.intent == INTENT_ASK:
        emit(
            run["id"],
            "clarify_requested",
            "Запрошено уточнение",
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
