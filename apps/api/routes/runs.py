from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from apps.api.auth import require_auth
from apps.api.models import ApprovalDecisionRequest, RunCreate
from core.agent import (
    analyze_tone,
    build_explicit_style_memory_payload,
    build_dynamic_prompt as build_agent_dynamic_prompt,
    build_tone_profile_memory_payload,
    merge_memory_payloads,
)
from core.brain.router import get_brain
from core.brain.types import LLMRequest
from core.chat_context import (
    build_chat_messages,
    build_user_profile_context,
    style_hint_from_preference,
)
from core.event_bus import emit
from core.intent_router import INTENT_ACT, INTENT_ASK, INTENT_CHAT, IntentDecision, IntentRouter
from core.llm_routing import ContextItem
from core.memory.interpreter import MemoryInterpretationError, interpret_user_message_for_memory
from core.skill_context import SkillContext
from core.semantic.decision import SemanticDecisionError
from core.skills.result_types import ArtifactCandidate, SkillResult, SourceCandidate
from memory.db import now_iso
from memory import store
from skills.memory_save import skill as memory_save_skill
from skills.web_research import skill as web_research_skill

router = APIRouter(prefix="/api/v1", tags=["runs"], dependencies=[Depends(require_auth)])

_APP_BASE_DIR = Path(__file__).resolve().parents[3]
_SOFT_RETRY_UNWANTED_PREFIXES = (
    "как ии", "как ai", "как языков", "извините",
    "я не могу", "я не должен", "против правил", "это нарушает",
    "согласно политике", "ограничения безопасности"
)
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_RELEVANCE_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
_FIRST_PERSON_RU_RE = re.compile(r"\b(я|мне|меня|мой|моя|моё|мои|мною)\b", flags=re.IGNORECASE)
_FIRST_PERSON_NARRATIVE_RU_RE = re.compile(
    r"\b(был|была|было|попал|попала|пришел|пришла|думал|думала|вспомнил|вспомнила|расскажу)\b",
    flags=re.IGNORECASE,
)
_RELEVANCE_STOPWORDS = {
    "как", "что", "это", "где", "когда", "почему", "зачем", "или", "и", "а", "но", "же",
    "ли", "по", "на", "в", "с", "к", "из", "о", "об", "для", "про", "у", "от", "до",
    "the", "and", "or", "for", "with", "from", "into", "about", "this", "that", "what", "how",
}
_TOPIC_ANCHOR_EXCLUDE = {
    "пытали", "пытать", "пытался", "пыталась",
    "сюжет", "история", "знаешь", "знаете",
    "объясни", "объяснить", "расскажи", "рассказать",
    "сделай", "сделать", "можно", "нужно", "помоги", "помочь",
    "why", "how", "what", "explain", "tell", "help",
}
_PROFILE_CORE_MEMORY_KEYS = {
    "user.name",
    "style.brevity",
    "style.tone",
    "style.mirror_level",
    "user.addressing.preference",
    "response.format",
}
_CONSTRAINT_HINT_RE = re.compile(
    r"\b("
    r"важно|обязательно|только|без|нужно|сначала|потом|ограничение|формат|"
    r"must|required|only|without|constraint|format"
    r")\b",
    flags=re.IGNORECASE,
)
_PRECISION_CRITICAL_QUERY_RE = re.compile(
    r"\b("
    r"формул\w*|formula\w*|числ\w*|number\w*|процент\w*|percent\w*|дата\w*|date\w*|время\w*|time\w*|"
    r"метрик\w*|metric\w*|kpi\w*|sql|regex|команд\w*|command\w*|верси\w*|version\w*|лимит\w*|limit\w*|"
    r"токен\w*|token\w*|бюджет\w*|budget\w*"
    r")\b",
    flags=re.IGNORECASE,
)
_AUTO_WEB_RESEARCH_INFO_QUERY_RE = re.compile(
    r"\b("
    r"кто|что|где|когда|почему|зачем|как|сколько|какой|какая|какие|чей|чья|чьи|"
    r"знаешь|знаете|расскажи|объясни|объяснить|сюжет|история|факт|факты|"
    r"who|what|where|when|why|how|explain|tell|fact|facts"
    r")\b",
    flags=re.IGNORECASE,
)
_AUTO_WEB_RESEARCH_UNCERTAIN_RE = re.compile(
    r"\b("
    r"не знаю|не уверен|не слышал|не слышала|не помню|не могу подтвердить|"
    r"возможно|наверное|предполагаю|скорее всего|может быть|"
    r"not sure|i don't know|i am not sure|maybe|probably|i guess|i think"
    r")\b",
    flags=re.IGNORECASE,
)
_AUTO_WEB_RESEARCH_ERROR_CODES = {
    "chat_empty_response",
    "connection_error",
    "http_error",
    "invalid_json",
    "model_not_found",
    "chat_llm_unhandled_error",
}
_FAST_CHAT_ACTION_RE = re.compile(
    r"\b("
    r"напомни|через\s+\d+|открой|запусти|выполни|кликни|нажми|перейди|удали|очисти|"
    r"отправь|оплати|переведи|создай\s+напомин|deploy|terminal|командн\w+\s+строк\w+|"
    r"браузер|browser|file|файл|папк\w+"
    r")\b",
    flags=re.IGNORECASE,
)
_FAST_CHAT_MEMORY_RE = re.compile(
    r"\b("
    r"запомни|сохрани\s+в\s+память|добавь\s+в\s+память|меня\s+\S+\s+зовут|меня\s+зовут|мо[её]\s+имя|"
    r"называй\s+меня|предпочитаю|remember\s+this|my\s+name\s+is|save\s+to\s+memory"
    r")\b",
    flags=re.IGNORECASE,
)
_FAST_CHAT_COMPLEX_QUERY_RE = re.compile(
    r"\b("
    r"план|пошаг|по\s+шаг|подроб|деталь|разбери|разбор|анализ|проанализ|сравни|сравнение|"
    r"стратег|roadmap|architecture|design|research|исслед|kpi|метрик|риск|"
    r"программ\w*\s+трениров|рацион|диет|сценар|вариант"
    r")\b",
    flags=re.IGNORECASE,
)
_FAST_CHAT_COMPLEX_DELIMITER_RE = re.compile(r"[\n;:]")
_FAST_CHAT_COMPLEX_MIN_WORDS = 18
_CHAT_RESPONSE_MODE_DIRECT = "direct_answer"
_CHAT_RESPONSE_MODE_PLAN = "step_by_step_plan"
_CHAT_RESPONSE_MODE_COMPLEX_MIN_WORDS = 16
_CHAT_RESPONSE_MODE_COMPLEX_WITH_DELIMITER_MIN_WORDS = 10
_CHAT_INFERENCE_PROFILE_FAST = "fast"
_CHAT_INFERENCE_PROFILE_BALANCED = "balanced"
_CHAT_INFERENCE_PROFILE_COMPLEX = "complex"
_INTERNAL_REASONING_TAG_RE = re.compile(
    r"<\s*(think|analysis|reasoning)\b[^>]*>.*?<\s*/\s*(think|analysis|reasoning)\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
_INTERNAL_REASONING_HEADER_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:reasoning|chain[- ]of[- ]thought|thought\s+process|internal\s+notes?|internal\s+reasoning|"
    r"внутренн(?:ие|яя)\s+(?:размышления|мысли|анализ)|ход\s+мыслей)\s*[:\-–]?\s*$",
    flags=re.IGNORECASE,
)
_FINAL_ANSWER_HEADER_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:final\s*answer|итог(?:овый)?\s*ответ)\s*[:\-–]?\s*",
    flags=re.IGNORECASE,
)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_REPEAT_PUNCT_RE = re.compile(r"([!?.,;:\-_=#*~])\1{3,}")
_URL_TEXT_RE = re.compile(r"https?://\S+", flags=re.IGNORECASE)
_SOURCES_HEADER_RE = re.compile(r"^\s*(?:источники|sources)\s*:\s*$", flags=re.IGNORECASE)
_TEMPLATE_PREFIXES = (
    "вот универсальный шаблон",
    "вот базовый шаблон",
    "вот общий шаблон",
    "вот общий ответ",
    "могу предложить общий шаблон",
    "уточните детали и я помогу",
)
_TEMPLATE_MARKERS = (
    "это зависит от контекста",
    "уточните детали",
    "общий шаблон",
    "универсальный шаблон",
    "базовый шаблон",
    "общий ответ",
)
_TOXIC_TARGET_RE = re.compile(
    r"\b(ты|тебе|тебя|тобой|твой|твоя|you|you're|youre|your)\b",
    flags=re.IGNORECASE,
)
_TOXIC_CONTEXT_ALLOW_RE = re.compile(
    r"\b(слово|термин|пример|цитат|ругатель|оскорб|мат|лексик|what\s+does|mean)\b",
    flags=re.IGNORECASE,
)
_TOXIC_RUDE_WORD_RE = re.compile(
    r"\b("
    r"дурак(?:а|у|ом|и)?|"
    r"идиот(?:а|у|ом|ы)?|"
    r"дебил(?:а|у|ом|ы)?|"
    r"кретин(?:а|у|ом|ы)?|"
    r"туп(?:ой|ая|ое|ые|ым|ыми|ого|ому|ых)?|"
    r"кринж(?:овый|овая|овое|овые)?|"
    r"stupid|idiot|moron"
    r")\b",
    flags=re.IGNORECASE,
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _chat_temperature_default() -> float:
    value = _env_float("ASTRA_LLM_CHAT_TEMPERATURE", 0.35)
    return max(0.1, min(1.0, value))


def _chat_top_p_default() -> float:
    value = _env_float("ASTRA_LLM_CHAT_TOP_P", 0.9)
    return max(0.0, min(1.0, value))


def _chat_repeat_penalty_default() -> float:
    value = _env_float("ASTRA_LLM_CHAT_REPEAT_PENALTY", 1.15)
    return max(1.0, value)


def _chat_num_predict_bounds(value: int) -> int:
    return max(64, min(2048, int(value)))


def _chat_num_predict_default() -> int:
    value = _env_int("ASTRA_LLM_OLLAMA_NUM_PREDICT", 256)
    return _chat_num_predict_bounds(value)


def _llm_fast_query_max_chars() -> int:
    value = _env_int("ASTRA_LLM_FAST_QUERY_MAX_CHARS", 120)
    return max(20, min(600, value))


def _llm_fast_query_max_words() -> int:
    value = _env_int("ASTRA_LLM_FAST_QUERY_MAX_WORDS", 18)
    return max(3, min(60, value))


def _llm_complex_query_min_chars() -> int:
    value = _env_int("ASTRA_LLM_COMPLEX_QUERY_MIN_CHARS", 260)
    return max(40, min(3000, value))


def _llm_complex_query_min_words() -> int:
    value = _env_int("ASTRA_LLM_COMPLEX_QUERY_MIN_WORDS", 45)
    return max(8, min(500, value))


def _clamp_float(value: float, *, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _select_chat_inference_profile(query_text: str, *, response_mode: str | None) -> tuple[str, str]:
    query = (query_text or "").strip()
    if not query:
        return _CHAT_INFERENCE_PROFILE_BALANCED, "empty_query"

    lowered = query.lower()
    words = [part for part in re.split(r"\s+", query) if part]
    complex_reasons: list[str] = []
    if response_mode == _CHAT_RESPONSE_MODE_PLAN:
        complex_reasons.append("response_mode_plan")
    if _FAST_CHAT_COMPLEX_QUERY_RE.search(lowered):
        complex_reasons.append("complex_keyword")
    if len(query) >= _llm_complex_query_min_chars():
        complex_reasons.append("complex_chars")
    if len(words) >= _llm_complex_query_min_words():
        complex_reasons.append("complex_words")
    if "```" in query:
        complex_reasons.append("code_block")
    if _FAST_CHAT_COMPLEX_DELIMITER_RE.search(query) and len(words) >= _CHAT_RESPONSE_MODE_COMPLEX_WITH_DELIMITER_MIN_WORDS:
        complex_reasons.append("structured_input")
    if complex_reasons:
        return _CHAT_INFERENCE_PROFILE_COMPLEX, "+".join(complex_reasons)

    if (
        len(query) <= _llm_fast_query_max_chars()
        and len(words) <= _llm_fast_query_max_words()
        and query.count("?") <= 1
        and not _FAST_CHAT_ACTION_RE.search(lowered)
        and not _FAST_CHAT_MEMORY_RE.search(lowered)
        and not _FAST_CHAT_COMPLEX_QUERY_RE.search(lowered)
    ):
        return _CHAT_INFERENCE_PROFILE_FAST, "short_query"

    return _CHAT_INFERENCE_PROFILE_BALANCED, "default"


def _chat_inference_settings(query_text: str, *, response_mode: str | None) -> dict[str, Any]:
    base_max_tokens = _chat_num_predict_default()
    base_temperature = _chat_temperature_default()
    base_top_p = _chat_top_p_default()
    base_repeat_penalty = _chat_repeat_penalty_default()
    profile, profile_reason = _select_chat_inference_profile(query_text, response_mode=response_mode)

    max_tokens = base_max_tokens
    temperature = base_temperature
    top_p = base_top_p
    repeat_penalty = base_repeat_penalty

    if profile == _CHAT_INFERENCE_PROFILE_FAST:
        max_tokens = _chat_num_predict_bounds(int(round(base_max_tokens * 0.7)))
        temperature = _clamp_float(base_temperature - 0.05, lower=0.1, upper=1.0)
        top_p = _clamp_float(base_top_p - 0.05, lower=0.0, upper=1.0)
        repeat_penalty = max(1.0, base_repeat_penalty + 0.05)
    elif profile == _CHAT_INFERENCE_PROFILE_COMPLEX:
        max_tokens = _chat_num_predict_bounds(int(round(base_max_tokens * 1.45)))
        temperature = _clamp_float(base_temperature - 0.08, lower=0.1, upper=1.0)
        top_p = _clamp_float(base_top_p + 0.03, lower=0.0, upper=1.0)
        repeat_penalty = max(1.0, base_repeat_penalty + 0.1)

    return {
        "profile": profile,
        "profile_reason": profile_reason,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "repeat_penalty": repeat_penalty,
    }


def _owner_direct_mode_enabled() -> bool:
    return _env_bool("ASTRA_OWNER_DIRECT_MODE", True)


def _fast_chat_path_enabled() -> bool:
    return _env_bool("ASTRA_CHAT_FAST_PATH_ENABLED", True)


def _fast_chat_max_chars() -> int:
    value = _env_int("ASTRA_CHAT_FAST_PATH_MAX_CHARS", 220)
    return max(60, min(600, value))


def _chat_auto_web_research_enabled() -> bool:
    return _env_bool("ASTRA_CHAT_AUTO_WEB_RESEARCH_ENABLED", True)


def _chat_auto_web_research_max_rounds() -> int:
    value = _env_int("ASTRA_CHAT_AUTO_WEB_RESEARCH_MAX_ROUNDS", 2)
    return max(1, min(4, value))


def _chat_auto_web_research_max_sources_total() -> int:
    value = _env_int("ASTRA_CHAT_AUTO_WEB_RESEARCH_MAX_SOURCES", 6)
    return max(1, min(16, value))


def _chat_auto_web_research_max_pages_fetch() -> int:
    value = _env_int("ASTRA_CHAT_AUTO_WEB_RESEARCH_MAX_PAGES", 4)
    return max(1, min(12, value))


def _chat_auto_web_research_depth() -> str:
    value = (os.getenv("ASTRA_CHAT_AUTO_WEB_RESEARCH_DEPTH") or "brief").strip().lower()
    if value in {"brief", "normal", "deep"}:
        return value
    return "brief"


def _chat_context_fetch_turns() -> int:
    value = _env_int("ASTRA_CHAT_CONTEXT_FETCH_TURNS", 24)
    return max(6, min(100, value))


def _chat_context_max_history_messages() -> int:
    value = _env_int("ASTRA_CHAT_CONTEXT_MAX_MESSAGES", 14)
    return max(4, min(40, value))


def _chat_context_min_recent_messages() -> int:
    value = _env_int("ASTRA_CHAT_CONTEXT_MIN_RECENT_MESSAGES", 4)
    return max(2, min(12, value))


def _chat_context_max_history_chars() -> int:
    value = _env_int("ASTRA_CHAT_CONTEXT_MAX_CHARS", 2200)
    return max(600, min(12000, value))


def _chat_context_message_max_chars() -> int:
    value = _env_int("ASTRA_CHAT_CONTEXT_MESSAGE_MAX_CHARS", 420)
    return max(120, min(1500, value))


def _chat_context_memory_fetch_limit() -> int:
    value = _env_int("ASTRA_CHAT_CONTEXT_MEMORY_FETCH_LIMIT", 60)
    return max(10, min(200, value))


def _chat_context_memory_max_items() -> int:
    value = _env_int("ASTRA_CHAT_CONTEXT_MEMORY_MAX_ITEMS", 20)
    return max(4, min(80, value))


def _chat_context_memory_max_chars() -> int:
    value = _env_int("ASTRA_CHAT_CONTEXT_MEMORY_MAX_CHARS", 1800)
    return max(400, min(8000, value))


def _chat_context_memory_item_max_chars() -> int:
    value = _env_int("ASTRA_CHAT_CONTEXT_MEMORY_ITEM_MAX_CHARS", 220)
    return max(80, min(800, value))


def _is_fast_chat_candidate(text: str, *, qa_mode: bool) -> bool:
    if qa_mode or not _fast_chat_path_enabled():
        return False
    query = (text or "").strip()
    if not query:
        return False
    if len(query) > _fast_chat_max_chars():
        return False
    words = [part for part in re.split(r"\s+", query) if part]
    if len(words) > _FAST_CHAT_COMPLEX_MIN_WORDS:
        return False
    lowered = query.lower()
    if _FAST_CHAT_ACTION_RE.search(lowered):
        return False
    if _FAST_CHAT_MEMORY_RE.search(lowered):
        return False
    if _FAST_CHAT_COMPLEX_QUERY_RE.search(lowered):
        return False
    if _FAST_CHAT_COMPLEX_DELIMITER_RE.search(query):
        return False
    if "," in query and len(words) >= 10:
        return False
    if query.count("?") > 1:
        return False
    return True


def _select_chat_response_mode(text: str) -> tuple[str, str]:
    query = (text or "").strip()
    if not query:
        return _CHAT_RESPONSE_MODE_DIRECT, "empty_query"
    lowered = query.lower()
    words = [part for part in re.split(r"\s+", query) if part]
    complex_reasons: list[str] = []
    if _FAST_CHAT_COMPLEX_QUERY_RE.search(lowered):
        complex_reasons.append("complex_keyword")
    if len(words) >= _CHAT_RESPONSE_MODE_COMPLEX_MIN_WORDS:
        complex_reasons.append("word_count")
    if query.count("?") > 1:
        complex_reasons.append("multi_question")
    if _FAST_CHAT_COMPLEX_DELIMITER_RE.search(query) and len(words) >= _CHAT_RESPONSE_MODE_COMPLEX_WITH_DELIMITER_MIN_WORDS:
        complex_reasons.append("structured_request")
    if "," in query and len(words) >= _CHAT_RESPONSE_MODE_COMPLEX_MIN_WORDS:
        complex_reasons.append("multi_clause")
    if complex_reasons:
        return _CHAT_RESPONSE_MODE_PLAN, "+".join(complex_reasons)
    return _CHAT_RESPONSE_MODE_DIRECT, "simple_query"


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


def _emit_intent_decided(
    run_id: str,
    decision,
    selected_mode: str | None,
    *,
    decision_latency_ms: int | None = None,
) -> None:
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
            "decision_latency_ms": decision_latency_ms,
        },
    )


def _build_runtime_metrics(
    *,
    intent: str,
    intent_path: str | None,
    decision_latency_ms: int | None,
    chat_response_mode: str | None = None,
    chat_response_mode_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "intent_path": intent_path,
        "decision_latency_ms": decision_latency_ms,
        "chat_response_mode": chat_response_mode,
        "chat_response_mode_reason": chat_response_mode_reason,
        "chat_inference_profile": None,
        "chat_inference_profile_reason": None,
        "llm_max_tokens": None,
        "llm_temperature": None,
        "llm_top_p": None,
        "llm_repeat_penalty": None,
        "context_history_messages": 0,
        "context_history_chars": 0,
        "context_memory_items": 0,
        "context_memory_chars": 0,
        "response_latency_ms": None,
        "auto_web_research_triggered": False,
        "auto_web_research_reason": None,
        "fallback_path": "none",
    }


def _event_payload_with_runtime_metrics(payload: dict[str, Any], runtime_metrics: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["runtime_metrics"] = dict(runtime_metrics)
    return result


def _chat_reason_code(fallback_path: str, *, degraded: bool) -> str:
    if fallback_path == "semantic_resilience":
        return "semantic_resilience_fallback"
    if fallback_path == "chat_llm_fallback":
        return "chat_llm_fallback"
    if fallback_path == "chat_llm_fallback_web_research":
        return "chat_llm_fallback_web_research"
    if fallback_path == "chat_web_research":
        return "chat_web_research"
    return "chat_response_degraded" if degraded else "chat_response_ok"


def _persist_runtime_metrics(run: dict[str, Any], runtime_metrics: dict[str, Any]) -> dict[str, Any]:
    run_id = str(run.get("id") or "").strip()
    if not run_id:
        return run
    meta = dict(run.get("meta") or {})
    meta["runtime_metrics"] = dict(runtime_metrics)
    updated = store.update_run_meta_and_mode(
        run_id,
        mode=str(run.get("mode") or "plan_only"),
        purpose=run.get("purpose"),
        meta=meta,
    )
    return updated or run


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


def _chat_fallback_steps(user_text: str, *, error_type: str | None = None) -> list[str]:
    query = (user_text or "").strip()
    lowered = query.lower()
    words = [part for part in re.split(r"\s+", query) if part]

    if _FAST_CHAT_ACTION_RE.search(lowered):
        return [
            "Укажи действие и целевое приложение/сайт одним предложением.",
            "Если нужно управление компьютером, используй режим execute_confirm/autopilot_safe.",
            "Пока модель восстанавливается, могу дать текстовый пошаговый план действий.",
        ]
    if _FAST_CHAT_COMPLEX_QUERY_RE.search(lowered) or len(words) >= 12:
        return [
            "Добавь 1-2 ограничения (срок, бюджет, уровень), чтобы план был точнее.",
            "Укажи формат: коротко или пошагово.",
            "После этого соберу структурный ответ без лишнего текста.",
        ]
    if _is_information_query(query):
        return [
            "Повтори запрос, и я попробую вернуть ответ через web research с проверкой источников.",
            "Если нужен быстрый ответ, напиши, что важнее: краткий итог или детали.",
            "Если нужны ссылки, явно добавь это в запрос.",
        ]
    if error_type == "budget_exceeded":
        return [
            "Повтори запрос позже или начни новый запуск.",
            "Если нужен короткий ответ, добавь в конце: 'коротко'.",
            "Если вопрос сложный, укажи приоритет — это ускорит следующий ответ.",
        ]
    return [
        "Повтори запрос одной фразой, чтобы стабилизировать контекст.",
        "Если хочешь краткий формат, добавь слово 'коротко'.",
        "Если нужен подробный разбор, укажи это прямо в запросе.",
    ]


def _chat_resilience_text(error_type: str | None, *, user_text: str = "") -> str:
    if error_type == "budget_exceeded":
        summary = "Лимит обращений к модели исчерпан для этого запуска."
    elif error_type and "llm_call_failed" in error_type:
        summary = "Локальная модель сейчас недоступна."
    elif error_type in {"model_not_found", "http_error", "connection_error", "invalid_json", "chat_empty_response"}:
        summary = "Локальная модель сейчас недоступна."
    else:
        summary = "Не удалось стабильно получить ответ от модели."

    query = _compact_text_for_context((user_text or "").strip(), 180)
    if query:
        summary = f"{summary} Текущий запрос: {query}."

    lines = [f"Краткий итог: {summary}", "", "Детали:"]
    for idx, step in enumerate(_chat_fallback_steps(user_text, error_type=error_type), start=1):
        lines.append(f"{idx}. {step}")
    return "\n".join(lines).strip()


def _save_memory_payload(run: dict, payload: dict[str, Any] | None, settings: dict[str, Any]) -> None:
    if not payload:
        return
    ctx = SimpleNamespace(run=run, task={}, plan_step={}, settings=settings)
    memory_save_skill.run(payload, ctx)


def _save_memory_payload_async(run: dict, payload: dict[str, Any] | None, settings: dict[str, Any]) -> None:
    if not payload:
        return

    run_snapshot = dict(run)
    payload_snapshot = dict(payload)
    settings_snapshot = dict(settings)

    def _worker() -> None:
        try:
            _save_memory_payload(run_snapshot, payload_snapshot, settings_snapshot)
        except Exception as exc:  # noqa: BLE001
            emit(
                run_snapshot.get("id") or "memory_save",
                "llm_request_failed",
                "Memory save failed",
                {
                    "provider": "local",
                    "model_id": None,
                    "reason_code": "memory_save_failed",
                    "error_type": "memory_save_failed",
                    "http_status_if_any": None,
                    "retry_count": 0,
                },
                level="warning",
            )

    threading.Thread(
        target=_worker,
        daemon=True,
        name=f"memory-save-{(run_snapshot.get('id') or 'run')[:8]}",
    ).start()


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
        hint = style_hint_from_preference(key, value)
        if hint:
            hints.append(hint)
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
        "content": summary.strip(),
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


def _style_hint_from_tone_analysis(tone_analysis: dict[str, Any] | None) -> str | None:
    if not isinstance(tone_analysis, dict):
        return None
    tone_type = str(tone_analysis.get("type") or "").strip().lower()
    mirror_level = str(tone_analysis.get("mirror_level") or "medium").strip().lower()

    if tone_type == "dry":
        return "Коротко и структурно: сначала ответ, затем шаги."
    if tone_type == "frustrated":
        return "Коротко валидируй состояние и сразу предложи конкретный план."
    if tone_type == "tired":
        return "Спокойный поддерживающий тон, без лишнего текста."
    if tone_type == "energetic":
        return "Живой темп и деловая конкретика."
    if tone_type == "crisis":
        return "Сначала стабилизация, затем короткий антикризисный план."
    if tone_type == "reflective":
        return "Спокойный вдумчивый тон с ясными выводами."
    if tone_type == "creative":
        return "Креативные варианты, но с прикладной структурой."
    if mirror_level == "low":
        return "Формально и точно, минимум разговорных вставок."
    return None


def _contextual_tone_adaptation_hint(query_text: str, tone_analysis: dict[str, Any] | None) -> str | None:
    if not isinstance(tone_analysis, dict):
        return None
    tone_type = str(tone_analysis.get("type") or "").strip().lower()
    hints: list[str] = []

    if tone_type in {"frustrated", "crisis"}:
        hints.append("Контекстный стиль: спокойный поддерживающий тон и сразу практические действия.")
    elif tone_type == "tired":
        hints.append("Контекстный стиль: мягкая компактная подача без перегруза.")
    elif tone_type == "energetic":
        hints.append("Контекстный стиль: быстрый ритм и деловая конкретика.")
    elif tone_type == "dry":
        hints.append("Контекстный стиль: строгая деловая подача и короткая структура.")
    elif tone_type == "reflective":
        hints.append("Контекстный стиль: вдумчивая подача с чёткими выводами.")

    precision_critical = bool(tone_analysis.get("task_complex")) or bool(_PRECISION_CRITICAL_QUERY_RE.search(query_text or ""))
    if precision_critical:
        hints.append("При адаптации тона не искажай факты, числа, имена, команды и ограничения запроса.")

    if not hints:
        return None
    return " ".join(hints[:2])


def _unique_style_hints(parts: list[str], *, limit: int = 5) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in parts:
        text = " ".join(str(raw or "").split()).strip()
        if not text:
            continue
        signature = text.lower()
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(text)
        if len(unique) >= limit:
            break
    return unique


def _build_effective_response_style_hint(
    *,
    decision_style_hint: str | None,
    interpreted_style_hint: str | None,
    tone_style_hint: str | None,
    profile_style_hints: list[str] | None,
    query_text: str,
    tone_analysis: dict[str, Any] | None,
) -> str | None:
    chunks: list[str] = []
    if isinstance(decision_style_hint, str) and decision_style_hint.strip():
        chunks.append(decision_style_hint)
    else:
        if isinstance(interpreted_style_hint, str) and interpreted_style_hint.strip():
            chunks.append(interpreted_style_hint)
        profile_values = profile_style_hints if isinstance(profile_style_hints, list) else []
        if profile_values:
            chunks.extend(str(item) for item in profile_values[:3] if isinstance(item, str) and item.strip())

    if isinstance(tone_style_hint, str) and tone_style_hint.strip():
        chunks.append(tone_style_hint)

    contextual_hint = _contextual_tone_adaptation_hint(query_text, tone_analysis)
    if contextual_hint:
        chunks.append(contextual_hint)

    merged = _unique_style_hints(chunks, limit=5)
    if not merged:
        return None
    return " ".join(merged)


def _build_chat_system_prompt(
    memories: list[dict],
    response_style_hint: str | None,
    owner_direct_mode: bool | None = None,
    *,
    response_mode: str = _CHAT_RESPONSE_MODE_DIRECT,
    user_message: str = "",
    history: list[dict] | None = None,
    tone_analysis: dict[str, Any] | None = None,
) -> str:
    if owner_direct_mode is None:
        owner_direct_mode = _owner_direct_mode_enabled()
    prompt, _analysis = build_agent_dynamic_prompt(
        memories,
        response_style_hint,
        user_message=user_message,
        history=history or [],
        owner_direct_mode=owner_direct_mode,
        tone_analysis=tone_analysis,
    )
    if _CYRILLIC_RE.search(user_message or ""):
        prompt = (
            f"{prompt}\n\n"
            "[Language Lock]\n"
            "- Отвечай только на русском языке.\n"
            "- Не переключайся на английский без явной просьбы владельца.\n"
            "- Английские слова допустимы только для кода/терминов."
        )
    selected_response_mode = (
        response_mode
        if response_mode in {_CHAT_RESPONSE_MODE_DIRECT, _CHAT_RESPONSE_MODE_PLAN}
        else _CHAT_RESPONSE_MODE_DIRECT
    )
    if selected_response_mode == _CHAT_RESPONSE_MODE_PLAN:
        prompt = (
            f"{prompt}\n\n"
            "[Response Mode]\n"
            "- Формат ответа: step-by-step plan.\n"
            "- Сначала краткий итог (1-2 предложения).\n"
            "- Затем нумерованные шаги 1..N.\n"
            "- Каждый шаг: что делать и какой результат ожидать."
        )
    else:
        prompt = (
            f"{prompt}\n\n"
            "[Response Mode]\n"
            "- Формат ответа: direct answer.\n"
            "- Дай прямой ответ сразу в 1-3 предложениях.\n"
            "- Шаги добавляй только если без них нельзя выполнить запрос."
        )
    prompt = (
        f"{prompt}\n\n"
        "[Internal Reasoning Policy]\n"
        "- Выполняй внутреннее рассуждение скрыто.\n"
        "- В ответе пользователю показывай только итог и полезные шаги.\n"
        "- Не выводи секции вида Reasoning/Internal notes/Внутренние размышления."
    )
    return prompt


def _is_likely_truncated_response(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.endswith(("...", "…", ":", ";", ",", "(", "[", "{", "—", "-")):
        return True
    if stripped.count("```") % 2 == 1:
        return True
    return False


def _is_ru_language_mismatch(user_text: str, response_text: str) -> bool:
    if not user_text.strip() or not response_text.strip():
        return False
    if not _CYRILLIC_RE.search(user_text):
        return False
    return not bool(_CYRILLIC_RE.search(response_text))


def _relevance_tokens(text: str) -> list[str]:
    return [token.lower() for token in _RELEVANCE_TOKEN_RE.findall(text or "")]


def _query_focus_tokens(text: str, *, limit: int = 8) -> list[str]:
    focus: list[str] = []
    seen: set[str] = set()
    for token in _relevance_tokens(text):
        if len(token) < 3 or token in _RELEVANCE_STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        focus.append(token)
        if len(focus) >= limit:
            break
    return focus


def _focus_overlap_count(focus_tokens: list[str], response_tokens: list[str]) -> int:
    if not focus_tokens or not response_tokens:
        return 0
    response_set = set(response_tokens)
    long_response_tokens = [token for token in response_set if len(token) >= 5]
    overlap = 0
    for focus in focus_tokens:
        if focus in response_set:
            overlap += 1
            continue
        if len(focus) < 5:
            continue
        stem = focus[:5]
        if any(token.startswith(stem) for token in long_response_tokens):
            overlap += 1
    return overlap


def _topic_anchor_tokens(focus_tokens: list[str]) -> list[str]:
    return [token for token in focus_tokens if token not in _TOPIC_ANCHOR_EXCLUDE]


def _compact_text_for_context(text: str, max_chars: int) -> str:
    compact = " ".join((text or "").split()).strip()
    if not compact:
        return ""
    if len(compact) <= max_chars:
        return compact
    if max_chars <= 1:
        return compact[:max_chars]
    return compact[: max_chars - 1].rstrip() + "…"


def _history_text_char_count(history: list[dict[str, Any]]) -> int:
    total = 0
    for item in history:
        content = item.get("content")
        if isinstance(content, str):
            total += len(content)
    return total


def _memory_meta_payload(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("meta")
    return meta if isinstance(meta, dict) else {}


def _memory_summary_text(item: dict[str, Any]) -> str:
    meta = _memory_meta_payload(item)
    summary = meta.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    content = item.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    title = item.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return ""


def _memory_is_profile_core(item: dict[str, Any]) -> bool:
    if bool(item.get("pinned")):
        return True
    meta = _memory_meta_payload(item)
    for field_name in ("facts", "preferences"):
        values = meta.get(field_name)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            key = value.get("key")
            if isinstance(key, str) and key.strip().lower() in _PROFILE_CORE_MEMORY_KEYS:
                return True
    title = str(item.get("title") or "").strip().lower()
    if "профиль" in title or "profile" in title:
        return True
    text = _memory_summary_text(item).lower()
    return "имя пользователя" in text


def _memory_text_char_count(memories: list[dict[str, Any]]) -> int:
    total = 0
    for item in memories:
        total += len(_memory_summary_text(item))
    return total


def _history_item_relevance_score(item: dict[str, Any], focus_tokens: list[str]) -> int:
    content = str(item.get("content") or "")
    if not content:
        return 0
    score = 0
    if focus_tokens:
        overlap = _focus_overlap_count(focus_tokens, _relevance_tokens(content))
        score += overlap * 4
    role = str(item.get("role") or "").strip().lower()
    if role == "user":
        score += 1
    if _CONSTRAINT_HINT_RE.search(content):
        score += 1
    return score


def _memory_item_relevance_score(item: dict[str, Any], focus_tokens: list[str]) -> int:
    text = _memory_summary_text(item)
    if not text:
        return 0
    score = 0
    if focus_tokens:
        overlap = _focus_overlap_count(focus_tokens, _relevance_tokens(text))
        score += overlap * 4
    if _memory_is_profile_core(item):
        score += 2
    if bool(item.get("pinned")):
        score += 2
    return score


def _select_chat_history_for_prompt(history: list[dict[str, Any]], *, user_text: str) -> list[dict[str, Any]]:
    max_messages = _chat_context_max_history_messages()
    min_recent = min(_chat_context_min_recent_messages(), max_messages)
    max_chars = _chat_context_max_history_chars()
    max_message_chars = _chat_context_message_max_chars()

    normalized: list[tuple[int, dict[str, Any]]] = []
    for idx, item in enumerate(history):
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content_raw = item.get("content")
        if not isinstance(content_raw, str):
            continue
        content = _compact_text_for_context(content_raw, max_message_chars)
        if not content:
            continue
        normalized.append(
            (
                idx,
                {
                    "role": role,
                    "content": content,
                    "ts": item.get("ts"),
                    "run_id": item.get("run_id"),
                },
            )
        )
    if not normalized:
        return []

    ordered = normalized
    if len(ordered) > max_messages:
        ordered_count = len(ordered)
        recent_start = max(0, ordered_count - min_recent)
        selected_positions: set[int] = set(range(recent_start, ordered_count))
        focus_tokens = _query_focus_tokens(user_text, limit=10)
        scored: list[tuple[int, int]] = []
        for position in range(recent_start):
            _, candidate = ordered[position]
            score = _history_item_relevance_score(candidate, focus_tokens)
            if score > 0:
                scored.append((score, position))
        scored.sort(key=lambda pair: (pair[0], pair[1]), reverse=True)
        for _score, position in scored:
            if len(selected_positions) >= max_messages:
                break
            selected_positions.add(position)
        for position in range(ordered_count - 1, -1, -1):
            if len(selected_positions) >= max_messages:
                break
            selected_positions.add(position)
        ordered = [ordered[position] for position in sorted(selected_positions)]

    ordered_count = len(normalized)
    recent_start = max(0, ordered_count - min_recent)
    recent_orig_indexes = {normalized[position][0] for position in range(recent_start, ordered_count)}
    selected_pairs = list(ordered)
    total_chars = sum(len(item.get("content") or "") for _, item in selected_pairs)
    while len(selected_pairs) > 1 and total_chars > max_chars:
        drop_pos = next(
            (pos for pos, (orig_idx, _item) in enumerate(selected_pairs) if orig_idx not in recent_orig_indexes),
            0,
        )
        _orig_idx, removed = selected_pairs.pop(drop_pos)
        total_chars -= len(removed.get("content") or "")

    return [item for _idx, item in selected_pairs]


def _select_profile_memories_for_prompt(memories: list[dict[str, Any]], *, user_text: str) -> list[dict[str, Any]]:
    max_items = _chat_context_memory_max_items()
    max_chars = _chat_context_memory_max_chars()
    max_item_chars = _chat_context_memory_item_max_chars()

    normalized: list[tuple[int, dict[str, Any]]] = []
    for idx, item in enumerate(memories):
        if not isinstance(item, dict):
            continue
        text = _compact_text_for_context(_memory_summary_text(item), max_item_chars)
        if not text:
            continue
        normalized_item = dict(item)
        meta = _memory_meta_payload(item)
        normalized_meta = dict(meta)
        summary = normalized_meta.get("summary")
        if isinstance(summary, str):
            normalized_meta["summary"] = _compact_text_for_context(summary, max_item_chars)
        normalized_item["meta"] = normalized_meta
        if isinstance(normalized_item.get("content"), str):
            normalized_item["content"] = _compact_text_for_context(str(normalized_item.get("content") or ""), max_item_chars)
        normalized.append((idx, normalized_item))
    if not normalized:
        return []

    focus_tokens = _query_focus_tokens(user_text, limit=10)
    core_positions = [pos for pos, (_idx, item) in enumerate(normalized) if _memory_is_profile_core(item)]
    selected_positions: list[int] = []
    selected_set: set[int] = set()
    for pos in core_positions:
        if pos in selected_set:
            continue
        selected_positions.append(pos)
        selected_set.add(pos)
        if len(selected_positions) >= max_items:
            break

    scored: list[tuple[int, int]] = []
    for pos, (_idx, item) in enumerate(normalized):
        if pos in selected_set:
            continue
        score = _memory_item_relevance_score(item, focus_tokens)
        if score > 0:
            scored.append((score, pos))
    scored.sort(key=lambda pair: (pair[0], -pair[1]), reverse=True)
    for _score, pos in scored:
        if len(selected_positions) >= max_items:
            break
        selected_positions.append(pos)
        selected_set.add(pos)

    for pos in range(len(normalized)):
        if len(selected_positions) >= max_items:
            break
        if pos in selected_set:
            continue
        selected_positions.append(pos)
        selected_set.add(pos)

    selected_positions.sort()
    selected_pairs = [normalized[pos] for pos in selected_positions]
    total_chars = sum(len(_memory_summary_text(item)) for _idx, item in selected_pairs)
    while len(selected_pairs) > 1 and total_chars > max_chars:
        drop_pos = next(
            (pos for pos, (_idx, item) in enumerate(selected_pairs) if not _memory_is_profile_core(item)),
            0,
        )
        _orig_idx, removed = selected_pairs.pop(drop_pos)
        total_chars -= len(_memory_summary_text(removed))

    return [item for _idx, item in selected_pairs]


def _is_likely_off_topic(user_text: str, response_text: str) -> bool:
    if not user_text.strip() or not response_text.strip():
        return False
    focus = _query_focus_tokens(user_text)
    if len(focus) < 2:
        return False
    response_tokens = _relevance_tokens(response_text)
    overlap = _focus_overlap_count(focus, response_tokens)
    query_words = [part for part in re.split(r"\s+", user_text.strip()) if part]
    anchor_focus = _topic_anchor_tokens(focus)
    if len(anchor_focus) >= 2:
        anchor_overlap = _focus_overlap_count(anchor_focus, response_tokens)
        if anchor_overlap == 0:
            return True
        if len(anchor_focus) >= 3 and len(query_words) <= 20 and anchor_overlap <= 1:
            return True
        critical_focus = [token for token in anchor_focus if len(token) >= 6]
        if critical_focus and _focus_overlap_count(critical_focus, response_tokens) == 0:
            return True
        if len(critical_focus) >= 2:
            critical_overlap = _focus_overlap_count(critical_focus, response_tokens)
            if critical_overlap <= len(critical_focus) - 1 and len(query_words) <= 20:
                return True
    if overlap == 0:
        return True
    return len(focus) >= 4 and len(query_words) <= 16 and overlap <= 1


def _is_unprompted_first_person_narrative(user_text: str, response_text: str) -> bool:
    if not response_text.strip():
        return False
    if _FIRST_PERSON_RU_RE.search(user_text):
        return False
    first_person_hits = _FIRST_PERSON_RU_RE.findall(response_text)
    if len(first_person_hits) < 1:
        return False
    return bool(_FIRST_PERSON_NARRATIVE_RU_RE.search(response_text))


def _has_unwanted_prefix(text: str) -> bool:
    lowered = text.strip().lower()
    return any(lowered.startswith(prefix) for prefix in _SOFT_RETRY_UNWANTED_PREFIXES)


def _is_template_like_answer(user_text: str, response_text: str) -> bool:
    value = " ".join((response_text or "").lower().split()).strip()
    if not value:
        return False
    if any(value.startswith(prefix) for prefix in _TEMPLATE_PREFIXES):
        return True

    lines = [line.strip().lower() for line in (response_text or "").splitlines() if line.strip()]
    if len(lines) >= 3 and len(set(lines)) <= max(1, len(lines) // 2):
        return True

    marker_hits = sum(1 for marker in _TEMPLATE_MARKERS if marker in value)
    if marker_hits < 2:
        return False

    focus = _query_focus_tokens(user_text)
    if not focus:
        return marker_hits >= 3
    overlap = _focus_overlap_count(focus, _relevance_tokens(response_text))
    return overlap <= 1


def _soft_retry_reason(user_text: str, text: str) -> str | None:
    if _has_unwanted_prefix(text):
        return "unwanted_prefix"
    if _is_ru_language_mismatch(user_text, text):
        return "ru_language_mismatch"
    if _is_template_like_answer(user_text, text):
        return "template_like"
    if _is_unprompted_first_person_narrative(user_text, text):
        return "off_topic"
    if _is_likely_off_topic(user_text, text):
        return "off_topic"
    if _is_likely_truncated_response(text):
        return "truncated"
    return None


def _last_user_message(messages: list[dict[str, Any]] | None) -> str:
    if not messages:
        return ""
    for item in reversed(messages):
        if str(item.get("role", "")).strip().lower() != "user":
            continue
        content = item.get("content")
        return content.strip() if isinstance(content, str) else ""
    return ""


def _call_chat_base_fallback(brain, request: LLMRequest, ctx) -> Any:
    # Switch purpose so router picks base chat model instead of tiered fast/complex model.
    fallback_request = replace(request, purpose="chat_response_base_fallback")
    try:
        fallback_response = brain.call(fallback_request, ctx)
    except Exception:  # noqa: BLE001
        return None
    if fallback_response.status == "ok" and (fallback_response.text or "").strip():
        return fallback_response
    return None


def _safe_retry_reason(user_text: str, text: str) -> str | None:
    if not (text or "").strip():
        return "empty_response"
    return _soft_retry_reason(user_text, text)


def _sanitize_user_visible_answer(text: str) -> str:
    cleaned = _INTERNAL_REASONING_TAG_RE.sub("", text or "").strip()
    if not cleaned:
        return ""
    lines = cleaned.splitlines()
    result: list[str] = []
    skipping_internal_block = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if not skipping_internal_block and result and result[-1] != "":
                result.append("")
            continue
        final_match = _FINAL_ANSWER_HEADER_RE.match(stripped)
        if final_match:
            skipping_internal_block = False
            tail = stripped[final_match.end() :].strip()
            if tail:
                result.append(tail)
            continue
        if _INTERNAL_REASONING_HEADER_RE.match(stripped):
            skipping_internal_block = True
            continue
        if skipping_internal_block:
            continue
        result.append(line)
    return "\n".join(result).strip()


def _normalize_for_dedupe(text: str) -> str:
    return " ".join((text or "").lower().split()).strip()


def _is_noise_block(text: str) -> bool:
    body = (text or "").strip()
    if not body:
        return True
    if _URL_TEXT_RE.search(body):
        return False
    printable = sum(1 for ch in body if not ch.isspace())
    if printable == 0:
        return True
    alnum = sum(1 for ch in body if ch.isalnum())
    symbols = printable - alnum
    if alnum <= 2 and printable >= 6:
        return True
    return symbols > max(8, alnum * 4)


def _is_toxic_noise_line(text: str) -> bool:
    body = " ".join((text or "").split()).strip()
    if not body:
        return False
    lowered = body.lower()
    if _TOXIC_CONTEXT_ALLOW_RE.search(lowered):
        return False
    if not _TOXIC_RUDE_WORD_RE.search(lowered):
        return False
    if _TOXIC_TARGET_RE.search(lowered):
        return True
    return len(lowered) <= 120


def _split_main_and_sources(text: str) -> tuple[str, str]:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    marker_idx: int | None = None
    for idx, line in enumerate(lines):
        if _SOURCES_HEADER_RE.match(line.strip()):
            marker_idx = idx
            break
    if marker_idx is None:
        return (text or "").strip(), ""
    main = "\n".join(lines[:marker_idx]).strip()
    sources = "\n".join(lines[marker_idx:]).strip()
    return main, sources


def _dedupe_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = " ".join((line or "").split()).strip()
        if not stripped:
            continue
        key = _normalize_for_dedupe(stripped)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(stripped)
    return result


def _extract_summary(block: str, *, max_chars: int = 220) -> str:
    compact = " ".join((block or "").split()).strip()
    if not compact:
        return ""
    lowered = compact.lower()
    if lowered.startswith("краткий итог:"):
        summary = compact.split(":", 1)[1].strip() if ":" in compact else compact
    else:
        sentence_match = re.search(r"(.+?[.!?…])(?:\s|$)", compact)
        summary = sentence_match.group(1).strip() if sentence_match else compact
    return _compact_text_for_context(summary, max_chars)


def _postprocess_user_visible_answer(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""

    normalized = _CONTROL_CHARS_RE.sub(" ", raw).replace("\uFFFD", "")
    normalized = _REPEAT_PUNCT_RE.sub(r"\1\1\1", normalized)
    normalized = "\n".join(line.rstrip() for line in normalized.splitlines()).strip()
    if not normalized:
        return ""

    main_text, sources_text = _split_main_and_sources(normalized)

    blocks: list[str] = []
    seen_blocks: set[str] = set()
    for block in re.split(r"\n\s*\n+", main_text):
        stripped = block.strip()
        if not stripped:
            continue
        candidate_lines: list[str] = []
        for line in stripped.splitlines():
            line_clean = " ".join(line.split()).strip()
            if not line_clean:
                continue
            if _is_noise_block(line_clean):
                continue
            if _is_toxic_noise_line(line_clean):
                continue
            candidate_lines.append(line_clean)
        deduped = _dedupe_lines(candidate_lines)
        if not deduped:
            continue
        cleaned_block = "\n".join(deduped).strip()
        if _is_noise_block(cleaned_block):
            continue
        key = _normalize_for_dedupe(cleaned_block)
        if not key or key in seen_blocks:
            continue
        seen_blocks.add(key)
        blocks.append(cleaned_block)

    final_main = ""
    if blocks:
        if len(blocks) == 1 and len(blocks[0]) <= 220 and "\n" not in blocks[0]:
            final_main = blocks[0]
        elif blocks[0].lower().startswith("краткий итог:"):
            final_main = "\n\n".join(blocks)
        else:
            summary = _extract_summary(blocks[0])
            details_blocks = list(blocks)
            if details_blocks:
                first_compact = " ".join(details_blocks[0].split()).strip()
                if summary and first_compact.lower().startswith(summary.lower()):
                    remainder = first_compact[len(summary) :].lstrip(" .:-")
                    if remainder:
                        details_blocks[0] = remainder
                    else:
                        details_blocks = details_blocks[1:]
            details = [item for item in details_blocks if item]
            if summary and details:
                final_main = f"Краткий итог: {summary}\n\nДетали:\n" + "\n\n".join(details)
            elif summary:
                final_main = f"Краткий итог: {summary}"
            else:
                final_main = "\n\n".join(blocks)

    final_sources = ""
    if sources_text:
        source_lines: list[str] = []
        for line in sources_text.splitlines():
            compact_line = " ".join(line.split()).strip()
            if not compact_line:
                continue
            if _is_noise_block(compact_line):
                continue
            source_lines.append(compact_line)
        if source_lines:
            header = source_lines[0]
            if not _SOURCES_HEADER_RE.match(header):
                source_lines.insert(0, "Источники:")
            else:
                source_lines[0] = "Источники:"
            final_source_lines = [source_lines[0]]
            seen_source_lines: set[str] = set()
            for line in source_lines[1:]:
                key = _normalize_for_dedupe(line)
                if not key or key in seen_source_lines:
                    continue
                seen_source_lines.add(key)
                final_source_lines.append(line)
            if len(final_source_lines) > 1:
                final_sources = "\n".join(final_source_lines)

    if final_main and final_sources:
        return f"{final_main}\n\n{final_sources}".strip()
    if final_main:
        return final_main.strip()
    return final_sources.strip()


def _finalize_user_visible_answer(text: str) -> str:
    sanitized = _sanitize_user_visible_answer(text)
    if not sanitized:
        return ""
    return _postprocess_user_visible_answer(sanitized)


def _call_chat_with_soft_retry(brain, request: LLMRequest, ctx) -> Any:
    response = brain.call(request, ctx)
    if response.status != "ok":
        return response

    user_text = _last_user_message(request.messages)
    reason = _safe_retry_reason(user_text, response.text or "")
    if not reason:
        return response

    # Deterministic pre-check: exactly one safe retry with the same chat context.
    retry_response = _call_chat_base_fallback(brain, request, ctx)
    if retry_response is None:
        return response

    retry_reason = _safe_retry_reason(user_text, retry_response.text or "")
    if retry_reason is None:
        return retry_response
    if reason == "empty_response":
        return retry_response
    return response


def _is_information_query(user_text: str) -> bool:
    query = (user_text or "").strip()
    if not query:
        return False
    lowered = query.lower()
    if _FAST_CHAT_ACTION_RE.search(lowered):
        return False
    if _FAST_CHAT_MEMORY_RE.search(lowered):
        return False
    if "?" in query:
        return True
    if _AUTO_WEB_RESEARCH_INFO_QUERY_RE.search(lowered):
        return True
    words = [part for part in re.split(r"\s+", query) if part]
    return len(words) >= 7


def _is_uncertain_response(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return True
    lowered = value.lower()
    if "предыдущий ответ вышел не по теме" in lowered:
        return True
    return bool(_AUTO_WEB_RESEARCH_UNCERTAIN_RE.search(lowered))


def _should_auto_web_research(user_text: str, response_text: str, *, error_type: str | None = None) -> bool:
    should_research, _ = _auto_web_research_decision(user_text, response_text, error_type=error_type)
    return should_research


def _auto_web_research_decision(user_text: str, response_text: str, *, error_type: str | None = None) -> tuple[bool, str | None]:
    if not _chat_auto_web_research_enabled():
        return False, None
    if not _is_information_query(user_text):
        return False, None
    if error_type in _AUTO_WEB_RESEARCH_ERROR_CODES:
        return True, f"llm_error:{error_type}"
    answer = (response_text or "").strip()
    if not answer:
        return True, "empty_response"
    soft_retry_reason = _soft_retry_reason(user_text, answer)
    if soft_retry_reason in {"off_topic", "ru_language_mismatch"}:
        return True, soft_retry_reason
    if _is_uncertain_response(answer):
        return True, "uncertain_response"
    return False, None


def _source_value(source: SourceCandidate | dict[str, Any], key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _artifact_value(artifact: ArtifactCandidate | dict[str, Any], key: str) -> Any:
    if isinstance(artifact, dict):
        return artifact.get(key)
    return getattr(artifact, key, None)


def _read_web_research_answer(result: SkillResult) -> str:
    artifacts = list(result.artifacts or [])
    artifacts.sort(key=lambda item: 0 if str(_artifact_value(item, "type") or "") == "web_research_answer_md" else 1)
    for artifact in artifacts:
        content_uri = str(_artifact_value(artifact, "content_uri") or "").strip()
        if not content_uri:
            continue
        path = Path(content_uri)
        if not path.is_absolute():
            path = _APP_BASE_DIR / path
        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception:  # noqa: BLE001
            continue
        if text:
            return text
    return ""


def _format_web_research_sources(sources: list[SourceCandidate | dict[str, Any]], *, limit: int = 5) -> str:
    lines: list[str] = []
    seen_urls: set[str] = set()
    for item in sources:
        url = str(_source_value(item, "url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = str(_source_value(item, "title") or "").strip()
        label = title or url
        lines.append(f"- {label} - {url}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def _compose_web_research_chat_text(result: SkillResult) -> str:
    answer = _read_web_research_answer(result)
    if not answer:
        summary = str(result.what_i_did or "").strip()
        if summary:
            answer = f"{summary}\n\nЯ проверил источники и собрал данные из интернета."
    sources_block = _format_web_research_sources(list(result.sources or []))
    if sources_block and "источники:" not in answer.lower():
        answer = f"{answer.strip()}\n\nИсточники:\n{sources_block}".strip()
    return answer.strip()


def _persist_web_research_result(run_id: str, result: SkillResult) -> None:
    try:
        existing_source_urls = {
            str(item.get("url") or "").strip()
            for item in store.list_sources(run_id)
            if str(item.get("url") or "").strip()
        }
        sources_payload: list[dict[str, Any]] = []
        for source in result.sources or []:
            url = str(_source_value(source, "url") or "").strip()
            if not url or url in existing_source_urls:
                continue
            existing_source_urls.add(url)
            sources_payload.append(
                {
                    "id": str(uuid.uuid4()),
                    "url": url,
                    "title": _source_value(source, "title"),
                    "domain": _source_value(source, "domain"),
                    "quality": _source_value(source, "quality"),
                    "retrieved_at": _source_value(source, "retrieved_at") or now_iso(),
                    "snippet": _source_value(source, "snippet"),
                    "pinned": bool(_source_value(source, "pinned")),
                }
            )
        if sources_payload:
            store.insert_sources(run_id, sources_payload)
    except Exception:  # noqa: BLE001
        pass

    try:
        existing_artifact_uris = {
            str(item.get("content_uri") or "").strip()
            for item in store.list_artifacts(run_id)
            if str(item.get("content_uri") or "").strip()
        }
        artifacts_payload: list[dict[str, Any]] = []
        for artifact in result.artifacts or []:
            content_uri = str(_artifact_value(artifact, "content_uri") or "").strip()
            if not content_uri or content_uri in existing_artifact_uris:
                continue
            existing_artifact_uris.add(content_uri)
            artifacts_payload.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": str(_artifact_value(artifact, "type") or "artifact"),
                    "title": str(_artifact_value(artifact, "title") or "Artifact"),
                    "content_uri": content_uri,
                    "created_at": _artifact_value(artifact, "created_at") or now_iso(),
                    "meta": _artifact_value(artifact, "meta") if isinstance(_artifact_value(artifact, "meta"), dict) else {},
                }
            )
        if artifacts_payload:
            store.insert_artifacts(run_id, artifacts_payload)
    except Exception:  # noqa: BLE001
        pass


def _emit_web_research_progress(run_id: str, events: list[dict[str, Any]] | None) -> None:
    for item in events or []:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        payload = {key: value for key, value in item.items() if key not in {"type", "message"}}
        emit(
            run_id,
            "task_progress",
            message,
            payload if isinstance(payload, dict) else {},
        )


def _run_auto_web_research(
    run: dict[str, Any],
    settings: dict[str, Any] | None,
    *,
    query_text: str,
    response_style_hint: str | None,
) -> dict[str, Any] | None:
    run_id = str(run.get("id") or "").strip()
    if not run_id:
        return None

    step_id = f"chat-web-research-step:{run_id}"
    task_id = f"chat-web-research-task:{run_id}"
    step = {
        "id": step_id,
        "run_id": run_id,
        "kind": "WEB_RESEARCH",
        "skill_name": "web_research",
        "title": "Chat auto web research",
    }
    task = {"id": task_id, "run_id": run_id}
    ctx = SkillContext(
        run=run,
        plan_step=step,
        task=task,
        settings=settings if isinstance(settings, dict) else {},
        base_dir=str(_APP_BASE_DIR),
    )
    inputs: dict[str, Any] = {
        "query": query_text.strip(),
        "mode": "deep",
        "depth": _chat_auto_web_research_depth(),
        "max_rounds": _chat_auto_web_research_max_rounds(),
        "max_sources_total": _chat_auto_web_research_max_sources_total(),
        "max_pages_fetch": _chat_auto_web_research_max_pages_fetch(),
    }
    if isinstance(response_style_hint, str) and response_style_hint.strip():
        inputs["style_hint"] = response_style_hint.strip()

    emit(
        run_id,
        "task_progress",
        "Проверяю данные в интернете",
        {"phase": "chat_auto_web_research_started", "query": query_text.strip()},
    )
    started_at = time.time()
    try:
        result = web_research_skill.run(inputs, ctx)
    except Exception as exc:  # noqa: BLE001
        emit(
            run_id,
            "task_progress",
            "Auto web research не удался",
            {"phase": "chat_auto_web_research_failed", "error": str(exc)},
            level="warning",
        )
        return None
    latency_ms = int((time.time() - started_at) * 1000)
    _emit_web_research_progress(run_id, result.events)
    text = _compose_web_research_chat_text(result)
    if not text:
        emit(
            run_id,
            "task_progress",
            "Auto web research не дал итогового ответа",
            {"phase": "chat_auto_web_research_empty"},
            level="warning",
        )
        return None

    if _soft_retry_reason(query_text, text) == "off_topic":
        emit(
            run_id,
            "task_progress",
            "Auto web research вернул нерелевантный ответ",
            {"phase": "chat_auto_web_research_off_topic", "query": query_text.strip()},
            level="warning",
        )
        return None

    _persist_web_research_result(run_id, result)
    emit(
        run_id,
        "task_progress",
        "Auto web research завершён",
        {
            "phase": "chat_auto_web_research_done",
            "sources_count": len(result.sources or []),
            "latency_ms": latency_ms,
            "confidence": result.confidence,
        },
    )
    return {
        "text": text,
        "latency_ms": latency_ms,
        "sources_count": len(result.sources or []),
        "confidence": result.confidence,
    }


@router.post("/projects/{project_id}/runs")
def create_run(project_id: str, payload: RunCreate, request: Request):
    run_started_at = time.time()
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
    if _is_fast_chat_candidate(payload.query_text, qa_mode=qa_mode):
        decision = IntentDecision(
            intent=INTENT_CHAT,
            confidence=0.55,
            reasons=["fast_chat_path"],
            questions=[],
            needs_clarification=False,
            act_hint=None,
            plan_hint=["CHAT_RESPONSE"],
            memory_item=None,
            response_style_hint=None,
            user_visible_note=None,
            decision_path="fast_chat_path",
        )
    else:
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
                    "reason_code": "semantic_decision_failed",
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
                    "reason_code": "semantic_decision_failed",
                    "error_type": "semantic_decision_unhandled_error",
                    "http_status_if_any": None,
                    "retry_count": 0,
                },
            )
            decision = _semantic_resilience_decision(semantic_error_code)

    decision_latency_ms = int((time.time() - run_started_at) * 1000)
    semantic_resilience = decision.decision_path == "semantic_resilience"
    fast_chat_path = decision.decision_path == "fast_chat_path"
    runtime_metrics = _build_runtime_metrics(
        intent=decision.intent,
        intent_path=decision.decision_path,
        decision_latency_ms=decision_latency_ms,
    )
    raw_profile_memories = store.list_user_memories(limit=_chat_context_memory_fetch_limit())
    profile_memories = _select_profile_memories_for_prompt(raw_profile_memories, user_text=payload.query_text)
    profile_context = build_user_profile_context(profile_memories)
    raw_history = store.list_recent_chat_turns(run.get("parent_run_id"), limit_turns=_chat_context_fetch_turns())
    history = _select_chat_history_for_prompt(raw_history, user_text=payload.query_text)
    runtime_metrics["context_history_messages"] = len(history)
    runtime_metrics["context_history_chars"] = _history_text_char_count(history)
    runtime_metrics["context_memory_items"] = len(profile_memories)
    runtime_metrics["context_memory_chars"] = _memory_text_char_count(profile_memories)
    tone_analysis = analyze_tone(payload.query_text, history, memories=profile_memories)
    memory_interpretation: dict[str, Any] | None = None
    memory_interpretation_error: str | None = None
    if semantic_resilience:
        memory_interpretation_error = "memory_interpreter_skipped_semantic_resilience"
    elif fast_chat_path:
        memory_interpretation_error = "memory_interpreter_skipped_fast_path"
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
                    "reason_code": "memory_interpretation_failed",
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
                    "reason_code": "memory_interpretation_failed",
                    "error_type": "memory_interpreter_unhandled_error",
                    "http_status_if_any": None,
                    "retry_count": 0,
                },
            )

    interpreted_style_hint = _style_hint_from_interpretation(memory_interpretation)
    tone_style_hint = _style_hint_from_tone_analysis(tone_analysis)
    profile_style_hints = profile_context.get("style_hints") if isinstance(profile_context.get("style_hints"), list) else []
    effective_response_style_hint = _build_effective_response_style_hint(
        decision_style_hint=decision.response_style_hint,
        interpreted_style_hint=interpreted_style_hint,
        tone_style_hint=tone_style_hint,
        profile_style_hints=profile_style_hints,
        query_text=payload.query_text,
        tone_analysis=tone_analysis,
    )
    chat_response_mode: str | None = None
    chat_response_mode_reason: str | None = None
    if decision.intent == INTENT_CHAT:
        chat_response_mode, chat_response_mode_reason = _select_chat_response_mode(payload.query_text)
    runtime_metrics["chat_response_mode"] = chat_response_mode
    runtime_metrics["chat_response_mode_reason"] = chat_response_mode_reason
    interpreted_user_name = _name_from_interpretation(memory_interpretation)
    if not interpreted_user_name:
        profile_name = profile_context.get("user_name")
        if isinstance(profile_name, str) and profile_name.strip():
            interpreted_user_name = profile_name.strip()
    memory_payload = _memory_payload_from_interpretation(payload.query_text, memory_interpretation)
    tone_memory_payload = None
    if memory_payload is None and bool((tone_analysis or {}).get("self_improve")):
        tone_memory_payload = build_tone_profile_memory_payload(payload.query_text, tone_analysis, profile_memories)
    memory_payload = merge_memory_payloads(memory_payload, tone_memory_payload)
    explicit_style_memory_payload = build_explicit_style_memory_payload(payload.query_text, profile_memories)
    memory_payload = merge_memory_payloads(memory_payload, explicit_style_memory_payload)

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
        "chat_response_mode": chat_response_mode,
        "chat_response_mode_reason": chat_response_mode_reason,
        "tone_analysis": tone_analysis,
        "character_mode": tone_analysis.get("primary_mode") if isinstance(tone_analysis, dict) else None,
        "supporting_mode": tone_analysis.get("supporting_mode") if isinstance(tone_analysis, dict) else None,
        "mode_history": tone_analysis.get("mode_history") if isinstance(tone_analysis, dict) else None,
        "user_visible_note": decision.user_visible_note,
        "user_name": interpreted_user_name,
        "semantic_error_code": semantic_error_code,
        "runtime_metrics": runtime_metrics,
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

    _emit_intent_decided(run["id"], decision, selected_mode, decision_latency_ms=decision_latency_ms)

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
        chat_started_at = time.time()
        if semantic_resilience:
            fallback_error = semantic_error_code or "semantic_resilience"
            fallback_text = _chat_resilience_text(fallback_error, user_text=payload.query_text)
            fallback_text = _finalize_user_visible_answer(fallback_text) or _chat_resilience_text(
                fallback_error,
                user_text=payload.query_text,
            )
            runtime_metrics["fallback_path"] = "semantic_resilience"
            runtime_metrics["response_latency_ms"] = int((time.time() - chat_started_at) * 1000)
            run = _persist_runtime_metrics(run, runtime_metrics)
            emit(
                run["id"],
                "chat_response_generated",
                "Ответ сформирован (degraded)",
                _event_payload_with_runtime_metrics(
                    {
                        "provider": "local",
                        "model_id": None,
                        "latency_ms": None,
                        "text": fallback_text,
                        "response_mode": chat_response_mode,
                        "response_mode_reason": chat_response_mode_reason,
                        "reason_code": _chat_reason_code("semantic_resilience", degraded=True),
                        "degraded": True,
                        "error_type": fallback_error,
                        "http_status_if_any": None,
                    },
                    runtime_metrics,
                ),
            )
            _save_memory_payload_async(run, memory_payload, settings)
            return {"kind": "chat", "intent": decision.to_dict(), "run": run, "chat_response": fallback_text}

        brain = get_brain()
        ctx = SimpleNamespace(run=run, task={}, plan_step={}, settings=settings)
        memories = profile_memories
        chat_history = history
        chat_tone_analysis = tone_analysis
        system_text = _build_chat_system_prompt(
            memories,
            effective_response_style_hint,
            response_mode=chat_response_mode or _CHAT_RESPONSE_MODE_DIRECT,
            user_message=payload.query_text,
            history=chat_history,
            tone_analysis=chat_tone_analysis,
        )
        chat_inference = _chat_inference_settings(
            payload.query_text,
            response_mode=chat_response_mode or _CHAT_RESPONSE_MODE_DIRECT,
        )
        runtime_metrics["chat_inference_profile"] = chat_inference["profile"]
        runtime_metrics["chat_inference_profile_reason"] = chat_inference["profile_reason"]
        runtime_metrics["llm_max_tokens"] = chat_inference["max_tokens"]
        runtime_metrics["llm_temperature"] = chat_inference["temperature"]
        runtime_metrics["llm_top_p"] = chat_inference["top_p"]
        runtime_metrics["llm_repeat_penalty"] = chat_inference["repeat_penalty"]
        llm_request = LLMRequest(
            purpose="chat_response",
            task_kind="chat",
            messages=build_chat_messages(system_text, chat_history, payload.query_text),
            context_items=[ContextItem(content=payload.query_text, source_type="user_prompt", sensitivity="personal")],
            max_tokens=chat_inference["max_tokens"],
            temperature=chat_inference["temperature"],
            top_p=chat_inference["top_p"],
            repeat_penalty=chat_inference["repeat_penalty"],
            run_id=run["id"],
            metadata={
                "chat_response_mode": chat_response_mode or _CHAT_RESPONSE_MODE_DIRECT,
                "chat_inference_profile": chat_inference["profile"],
                "chat_inference_profile_reason": chat_inference["profile_reason"],
            },
        )
        fallback_text: str | None = None
        fallback_provider = "local"
        fallback_model_id = None
        fallback_latency_ms = None
        fallback_error_type: str | None = None
        fallback_http_status: int | None = None
        try:
            response = _call_chat_with_soft_retry(brain, llm_request, ctx)
        except Exception as exc:  # noqa: BLE001
            fallback_error_type = str(getattr(exc, "error_type", "chat_llm_unhandled_error"))
            fallback_http_status = getattr(exc, "status_code", None)
            fallback_provider = str(getattr(exc, "provider", "local") or "local")
            fallback_model_id = getattr(exc, "model_id", None)
            fallback_text = _chat_resilience_text(fallback_error_type, user_text=payload.query_text)
            emit(
                run["id"],
                "llm_request_failed",
                "Chat LLM failed",
                {
                    "provider": fallback_provider,
                    "model_id": fallback_model_id,
                    "reason_code": "chat_llm_failed",
                    "error_type": fallback_error_type,
                    "http_status_if_any": fallback_http_status,
                    "retry_count": 0,
                },
            )
        else:
            clean_response_text = _finalize_user_visible_answer(response.text or "")
            if response.status != "ok" or not (response.text or "").strip():
                fallback_error_type = response.error_type or "chat_empty_response"
                fallback_provider = response.provider or "local"
                fallback_model_id = response.model_id
                fallback_latency_ms = response.latency_ms
                fallback_text = _chat_resilience_text(fallback_error_type, user_text=payload.query_text)
            elif not clean_response_text:
                fallback_error_type = "chat_empty_response"
                fallback_provider = response.provider or "local"
                fallback_model_id = response.model_id
                fallback_latency_ms = response.latency_ms
                fallback_text = _chat_resilience_text(fallback_error_type, user_text=payload.query_text)
            else:
                response = replace(response, text=clean_response_text)

        if fallback_text is not None:
            fallback_text = _finalize_user_visible_answer(fallback_text) or _chat_resilience_text(
                fallback_error_type,
                user_text=payload.query_text,
            )
            should_auto_web_research, auto_web_research_reason = _auto_web_research_decision(
                payload.query_text,
                fallback_text,
                error_type=fallback_error_type,
            )
            if should_auto_web_research:
                runtime_metrics["auto_web_research_triggered"] = True
                runtime_metrics["auto_web_research_reason"] = auto_web_research_reason
                researched = _run_auto_web_research(
                    run,
                    settings,
                    query_text=payload.query_text,
                    response_style_hint=effective_response_style_hint,
                )
                if researched is not None:
                    researched_text = _finalize_user_visible_answer(str(researched.get("text") or ""))
                    if not researched_text:
                        researched_text = str(researched.get("text") or "").strip()
                    if researched_text:
                        runtime_metrics["fallback_path"] = "chat_llm_fallback_web_research"
                        runtime_metrics["response_latency_ms"] = int((time.time() - chat_started_at) * 1000)
                        run = _persist_runtime_metrics(run, runtime_metrics)
                        emit(
                            run["id"],
                            "chat_response_generated",
                            "Ответ сформирован (web research)",
                            _event_payload_with_runtime_metrics(
                                {
                                    "provider": "web_research",
                                    "model_id": "web_research",
                                    "latency_ms": researched.get("latency_ms"),
                                    "text": researched_text,
                                    "response_mode": chat_response_mode,
                                    "response_mode_reason": chat_response_mode_reason,
                                    "reason_code": _chat_reason_code("chat_llm_fallback_web_research", degraded=False),
                                    "degraded": False,
                                    "sources_count": researched.get("sources_count"),
                                    "confidence": researched.get("confidence"),
                                },
                                runtime_metrics,
                            ),
                        )
                        _save_memory_payload_async(run, memory_payload, settings)
                        return {
                            "kind": "chat",
                            "intent": decision.to_dict(),
                            "run": run,
                            "chat_response": researched_text,
                        }
            runtime_metrics["fallback_path"] = "chat_llm_fallback"
            runtime_metrics["response_latency_ms"] = int((time.time() - chat_started_at) * 1000)
            run = _persist_runtime_metrics(run, runtime_metrics)
            emit(
                run["id"],
                "chat_response_generated",
                "Ответ сформирован (degraded)",
                _event_payload_with_runtime_metrics(
                    {
                        "provider": fallback_provider,
                        "model_id": fallback_model_id,
                        "latency_ms": fallback_latency_ms,
                        "text": fallback_text,
                        "response_mode": chat_response_mode,
                        "response_mode_reason": chat_response_mode_reason,
                        "reason_code": _chat_reason_code("chat_llm_fallback", degraded=True),
                        "degraded": True,
                        "error_type": fallback_error_type,
                        "http_status_if_any": fallback_http_status,
                    },
                    runtime_metrics,
                ),
            )
            _save_memory_payload_async(run, memory_payload, settings)
            return {"kind": "chat", "intent": decision.to_dict(), "run": run, "chat_response": fallback_text}

        should_auto_web_research, auto_web_research_reason = _auto_web_research_decision(
            payload.query_text,
            response.text or "",
            error_type=None,
        )
        if should_auto_web_research:
            runtime_metrics["auto_web_research_triggered"] = True
            runtime_metrics["auto_web_research_reason"] = auto_web_research_reason
            researched = _run_auto_web_research(
                run,
                settings,
                query_text=payload.query_text,
                response_style_hint=effective_response_style_hint,
            )
            if researched is not None:
                researched_text = _finalize_user_visible_answer(str(researched.get("text") or ""))
                if not researched_text:
                    researched_text = str(researched.get("text") or "").strip()
                if researched_text:
                    runtime_metrics["fallback_path"] = "chat_web_research"
                    runtime_metrics["response_latency_ms"] = int((time.time() - chat_started_at) * 1000)
                    run = _persist_runtime_metrics(run, runtime_metrics)
                    emit(
                        run["id"],
                        "chat_response_generated",
                        "Ответ сформирован (web research)",
                        _event_payload_with_runtime_metrics(
                            {
                                "provider": "web_research",
                                "model_id": "web_research",
                                "latency_ms": researched.get("latency_ms"),
                                "text": researched_text,
                                "response_mode": chat_response_mode,
                                "response_mode_reason": chat_response_mode_reason,
                                "reason_code": _chat_reason_code("chat_web_research", degraded=False),
                                "degraded": False,
                                "sources_count": researched.get("sources_count"),
                                "confidence": researched.get("confidence"),
                            },
                            runtime_metrics,
                        ),
                    )
                    _save_memory_payload_async(run, memory_payload, settings)
                    return {
                        "kind": "chat",
                        "intent": decision.to_dict(),
                        "run": run,
                        "chat_response": researched_text,
                    }

        runtime_metrics["response_latency_ms"] = int((time.time() - chat_started_at) * 1000)
        run = _persist_runtime_metrics(run, runtime_metrics)
        emit(
            run["id"],
            "chat_response_generated",
            "Ответ сформирован",
            _event_payload_with_runtime_metrics(
                {
                    "provider": response.provider,
                    "model_id": response.model_id,
                    "latency_ms": response.latency_ms,
                    "text": response.text,
                    "response_mode": chat_response_mode,
                    "response_mode_reason": chat_response_mode_reason,
                    "reason_code": _chat_reason_code("none", degraded=False),
                },
                runtime_metrics,
            ),
        )
        _save_memory_payload_async(run, memory_payload, settings)
        return {"kind": "chat", "intent": decision.to_dict(), "run": run, "chat_response": response.text}

    if decision.intent == INTENT_ASK:
        emit(
            run["id"],
            "clarify_requested",
            "Запрошено уточнение",
            {"questions": decision.questions},
        )
        _save_memory_payload_async(run, memory_payload, settings)
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
