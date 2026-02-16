from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.brain.router import get_brain
from core.brain.types import LLMRequest
from core.llm_routing import ContextItem

MIN_STORE_CONFIDENCE = 0.55


class MemoryInterpretationError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail or code
        super().__init__(f"{code}: {self.detail}")


def _load_prompt() -> str:
    path = Path(__file__).resolve().parents[2] / "prompts" / "memory_interpreter.txt"
    return path.read_text(encoding="utf-8").strip()


def _schema() -> dict[str, Any]:
    fact_item = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
            "confidence": {"type": "number"},
            "evidence": {"type": "string"},
        },
        "required": ["key", "value", "confidence", "evidence"],
        "additionalProperties": False,
    }
    pref_item = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
            "confidence": {"type": "number"},
            "evidence": {"type": ["string", "null"]},
        },
        "required": ["key", "value", "confidence"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "should_store": {"type": "boolean"},
            "confidence": {"type": "number"},
            "facts": {"type": "array", "items": fact_item},
            "preferences": {"type": "array", "items": pref_item},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "possible_facts": {"type": "array", "items": fact_item},
        },
        "required": ["should_store", "confidence", "facts", "preferences", "title", "summary"],
        "additionalProperties": False,
    }


def _clean_text(value: Any, *, field: str, required: bool = True) -> str:
    if value is None:
        if required:
            raise MemoryInterpretationError("memory_interpreter_invalid_field", f"{field} is required")
        return ""
    if not isinstance(value, str):
        raise MemoryInterpretationError("memory_interpreter_invalid_field", f"{field} must be string")
    cleaned = " ".join(value.strip().split())
    if required and not cleaned:
        raise MemoryInterpretationError("memory_interpreter_invalid_field", f"{field} is empty")
    return cleaned


def _clean_confidence(value: Any, *, field: str) -> float:
    if not isinstance(value, (int, float)):
        raise MemoryInterpretationError("memory_interpreter_invalid_confidence", f"{field} must be number")
    num = float(value)
    if num < 0.0 or num > 1.0:
        raise MemoryInterpretationError("memory_interpreter_invalid_confidence", f"{field} must be in [0, 1]")
    return num


def _parse_fact_item(item: Any, user_text: str, *, field: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise MemoryInterpretationError("memory_interpreter_invalid_fact", f"{field} entries must be objects")
    key = _clean_text(item.get("key"), field=f"{field}.key")
    value = _clean_text(item.get("value"), field=f"{field}.value")
    confidence = _clean_confidence(item.get("confidence"), field=f"{field}.confidence")
    evidence = _clean_text(item.get("evidence"), field=f"{field}.evidence")
    if evidence not in user_text:
        raise MemoryInterpretationError(
            "memory_interpreter_invalid_evidence",
            f"{field}.evidence must be substring of user message",
        )
    return {
        "key": key,
        "value": value,
        "confidence": confidence,
        "evidence": evidence,
    }


def _parse_pref_item(item: Any, user_text: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise MemoryInterpretationError("memory_interpreter_invalid_preference", "preferences entries must be objects")
    key = _clean_text(item.get("key"), field="preferences.key")
    value = _clean_text(item.get("value"), field="preferences.value")
    confidence = _clean_confidence(item.get("confidence"), field="preferences.confidence")
    evidence_raw = item.get("evidence")
    evidence = None
    if evidence_raw is not None:
        evidence = _clean_text(evidence_raw, field="preferences.evidence")
        if evidence not in user_text:
            raise MemoryInterpretationError(
                "memory_interpreter_invalid_evidence",
                "preferences.evidence must be substring of user message",
            )
    result = {"key": key, "value": value, "confidence": confidence}
    if evidence:
        result["evidence"] = evidence
    return result


def _safe_history(history: list[dict] | None) -> list[dict[str, str]]:
    if not history:
        return []
    result: list[dict[str, str]] = []
    for item in history[-10:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        result.append({"role": role, "content": text})
    return result


def _parse_response(text: str, user_text: str) -> dict[str, Any]:
    raw_text = (text or "").strip()
    if not raw_text:
        raise MemoryInterpretationError("memory_interpreter_empty_response")
    try:
        payload = json.loads(raw_text)
    except Exception as exc:  # noqa: BLE001
        raise MemoryInterpretationError("memory_interpreter_invalid_json", str(exc)) from exc
    if not isinstance(payload, dict):
        raise MemoryInterpretationError("memory_interpreter_invalid_payload", "response must be JSON object")

    should_store = payload.get("should_store")
    if not isinstance(should_store, bool):
        raise MemoryInterpretationError("memory_interpreter_invalid_should_store", "should_store must be boolean")
    confidence = _clean_confidence(payload.get("confidence"), field="confidence")

    facts_raw = payload.get("facts")
    if not isinstance(facts_raw, list):
        raise MemoryInterpretationError("memory_interpreter_invalid_facts", "facts must be array")
    facts = [_parse_fact_item(item, user_text, field="facts") for item in facts_raw]

    prefs_raw = payload.get("preferences")
    if not isinstance(prefs_raw, list):
        raise MemoryInterpretationError("memory_interpreter_invalid_preferences", "preferences must be array")
    preferences = [_parse_pref_item(item, user_text) for item in prefs_raw]

    title = _clean_text(payload.get("title"), field="title")
    summary = _clean_text(payload.get("summary"), field="summary")

    possible_facts_raw = payload.get("possible_facts")
    possible_facts: list[dict[str, Any]] = []
    if isinstance(possible_facts_raw, list):
        possible_facts = [_parse_fact_item(item, user_text, field="possible_facts") for item in possible_facts_raw]
    elif possible_facts_raw is not None:
        raise MemoryInterpretationError("memory_interpreter_invalid_possible_facts", "possible_facts must be array")

    if should_store and confidence < MIN_STORE_CONFIDENCE:
        should_store = False

    return {
        "should_store": should_store,
        "confidence": confidence,
        "facts": facts,
        "preferences": preferences,
        "title": title,
        "summary": summary,
        "possible_facts": possible_facts,
    }


def interpret_user_message_for_memory(
    user_text: str,
    history: list[dict],
    known_profile: dict | None,
    *,
    model_kind: str = "chat",
    brain=None,
    run_id: str | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = (user_text or "").strip()
    if not text:
        return {
            "should_store": False,
            "confidence": 0.0,
            "facts": [],
            "preferences": [],
            "title": "Профиль пользователя",
            "summary": "",
            "possible_facts": [],
        }

    brain = brain or get_brain()
    prompt = _load_prompt()

    profile_payload = known_profile if isinstance(known_profile, dict) else {}
    body = {
        "user_text": text,
        "history": _safe_history(history),
        "known_profile": profile_payload,
    }

    privacy_settings = dict(settings or {})
    privacy = dict(privacy_settings.get("privacy") or {})
    privacy.update({"strict_local": True, "cloud_allowed": False, "auto_cloud_enabled": False})
    privacy_settings["privacy"] = privacy
    llm_ctx = SimpleNamespace(run={"id": run_id} if run_id else {}, task={}, plan_step={}, settings=privacy_settings)

    request = LLMRequest(
        purpose="memory_interpreter",
        task_kind="memory_interpretation",
        run_id=run_id,
        preferred_model_kind=model_kind,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        ],
        context_items=[ContextItem(content=text, source_type="user_prompt", sensitivity="personal")],
        temperature=0.1,
        max_tokens=700,
        json_schema=_schema(),
    )

    try:
        response = brain.call(request, llm_ctx)
    except Exception as exc:  # noqa: BLE001
        raise MemoryInterpretationError("memory_interpreter_llm_call_failed", str(exc)) from exc

    if response.status != "ok":
        raise MemoryInterpretationError("memory_interpreter_llm_failed", response.error_type or response.status)

    return _parse_response(response.text or "", text)
