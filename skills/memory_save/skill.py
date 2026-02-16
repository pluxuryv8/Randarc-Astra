from __future__ import annotations

import re
from typing import Any

from core.event_bus import emit
from core.memory_normalize import normalize_memory_texts
from core.skills.result_types import SkillResult
from memory import store

MAX_FACT_LEN = 220
MAX_SUMMARY_LEN = 320


def _truncate_fact(text: str) -> str:
    if len(text) <= MAX_FACT_LEN:
        return text
    return text[: MAX_FACT_LEN - 3].rstrip() + "..."


def _ensure_period(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    if stripped[-1] in ".!?":
        return stripped
    return stripped + "."


def _normalize_fact(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return ""
    return _ensure_period(cleaned)


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower().replace("ё", "е"))


def _dedup_fact(fact: str, existing: list[dict]) -> str | None:
    if not fact:
        return None
    norm_fact = _norm(fact)
    if not norm_fact:
        return None
    existing_norm = {_norm(item.get("content", "")) for item in existing if isinstance(item, dict)}
    if norm_fact in existing_norm:
        return None
    return fact


def _clean_confidence(value: Any) -> float:
    if isinstance(value, (int, float)):
        num = float(value)
        if num < 0.0:
            return 0.0
        if num > 1.0:
            return 1.0
        return num
    return 0.0


def _normalize_kv_items(
    values: Any,
    *,
    require_evidence: bool,
    limit: int,
) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    result: list[dict[str, Any]] = []
    for item in values:
        if len(result) >= limit:
            break
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        confidence = _clean_confidence(item.get("confidence"))
        evidence = item.get("evidence")

        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(value, str) or not value.strip():
            continue

        payload: dict[str, Any] = {"key": key.strip(), "value": value.strip(), "confidence": confidence}
        if isinstance(evidence, str) and evidence.strip():
            payload["evidence"] = evidence.strip()
        elif require_evidence:
            continue
        result.append(payload)
    return result


def _structured_payload(inputs: dict, content: str) -> dict[str, Any] | None:
    raw = inputs.get("memory_payload") if isinstance(inputs, dict) else None
    if not isinstance(raw, dict):
        return None

    title = raw.get("title") if isinstance(raw.get("title"), str) else "Профиль пользователя"
    summary = raw.get("summary") if isinstance(raw.get("summary"), str) else ""
    summary = summary.strip()
    if not summary:
        raise RuntimeError("memory_payload_summary_missing")

    facts = _normalize_kv_items(raw.get("facts"), require_evidence=True, limit=12)
    preferences = _normalize_kv_items(raw.get("preferences"), require_evidence=False, limit=12)
    possible_facts = _normalize_kv_items(raw.get("possible_facts"), require_evidence=True, limit=12)

    return {
        "title": title.strip() or "Профиль пользователя",
        "summary": summary,
        "meta": {
            "schema": "memory_interpretation.v1",
            "summary": summary,
            "confidence": _clean_confidence(raw.get("confidence")),
            "facts": facts,
            "preferences": preferences,
            "possible_facts": possible_facts,
        },
    }


def _single_fact_from_inputs(inputs: dict, content: str, ctx) -> str | None:
    raw_facts = inputs.get("facts") if isinstance(inputs, dict) and isinstance(inputs.get("facts"), list) else []
    prepared = [str(item).strip() for item in raw_facts if isinstance(item, (str, int, float)) and str(item).strip()]
    if prepared:
        return prepared[0]

    normalized = normalize_memory_texts(content, settings=ctx.settings)
    if not normalized:
        return None
    return normalized[0]


def run(inputs: dict, ctx) -> SkillResult:
    run_id = ctx.run["id"]
    raw_content = inputs.get("content") if isinstance(inputs, dict) else None
    content = raw_content.strip() if isinstance(raw_content, str) else ""
    title = inputs.get("title") if isinstance(inputs, dict) and isinstance(inputs.get("title"), str) else None
    tags = inputs.get("tags") if isinstance(inputs, dict) and isinstance(inputs.get("tags"), list) else None
    origin = inputs.get("origin") if isinstance(inputs, dict) and isinstance(inputs.get("origin"), str) else "user_command"

    if not content:
        content = (ctx.run.get("query_text") or "").strip()

    emit(
        run_id,
        "memory_save_requested",
        "Запрошено сохранение в память",
        {"from": origin, "preview_len": len(content)},
        task_id=ctx.task.get("id"),
        step_id=ctx.plan_step.get("id"),
    )

    try:
        existing = store.list_user_memories(limit=200)
    except Exception:
        existing = []

    structured = _structured_payload(inputs, content)
    if structured:
        summary = _truncate_fact(_normalize_fact(structured["summary"][:MAX_SUMMARY_LEN]))
        summary = _dedup_fact(summary, existing)
        if not summary:
            if origin == "auto":
                return SkillResult(what_i_did="Нет новых фактов для сохранения.", confidence=0.3)
            raise RuntimeError("memory_extract_empty")

        structured_meta = structured.get("meta") if isinstance(structured.get("meta"), dict) else {}
        memory = store.create_user_memory(
            title or structured["title"],
            summary,
            tags,
            source=origin,
            meta=structured_meta,
        )
        emit(
            run_id,
            "memory_saved",
            "Память сохранена",
            {
                "memory_id": memory["id"],
                "title": memory["title"],
                "len": len(memory["content"]),
                "tags_count": len(memory["tags"] or []),
                "origin": origin,
            },
            task_id=ctx.task.get("id"),
            step_id=ctx.plan_step.get("id"),
        )
        return SkillResult(what_i_did="Записано фактов: 1.", confidence=1.0)

    fact = _single_fact_from_inputs(inputs, content, ctx)
    if not fact:
        if origin == "auto":
            return SkillResult(what_i_did="Нет новых фактов для сохранения.", confidence=0.3)
        raise RuntimeError("memory_extract_empty")

    fact = _truncate_fact(_normalize_fact(fact))
    fact = _dedup_fact(fact, existing)
    if not fact:
        if origin == "auto":
            return SkillResult(what_i_did="Нет новых фактов для сохранения.", confidence=0.3)
        raise RuntimeError("memory_extract_empty")

    memory = store.create_user_memory(title, fact, tags, source=origin, meta={})
    emit(
        run_id,
        "memory_saved",
        "Память сохранена",
        {
            "memory_id": memory["id"],
            "title": memory["title"],
            "len": len(memory["content"]),
            "tags_count": len(memory["tags"] or []),
            "origin": origin,
        },
        task_id=ctx.task.get("id"),
        step_id=ctx.plan_step.get("id"),
    )

    return SkillResult(what_i_did="Записано фактов: 1.", confidence=1.0)
