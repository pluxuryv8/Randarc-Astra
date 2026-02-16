from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.brain.router import get_brain
from core.brain.types import LLMRequest
from core.llm_routing import ContextItem

VALID_INTENTS = {"CHAT", "ACT", "ASK_CLARIFY"}
DEFAULT_ACTIONS: dict[str, list[dict]] = {
    "save_memory": [],
    "save_preferences": [],
    "create_reminders": [],
    "web_research": [],
}


@dataclass
class IntentActionsResult:
    intent: str
    confidence: float
    actions: dict[str, list[dict]]
    raw: dict[str, Any] | None = None


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\\s*|```\\s*$", re.IGNORECASE)
_NAME_EVIDENCE_RE = re.compile(
    r"(меня\s+(?:[A-Za-zА-Яа-яЁё-]{2,}\s+)?зовут|зови меня|можно звать|мо[её] имя|мое имя|обращайся ко мне)",
    re.IGNORECASE,
)


def _load_system_prompt() -> str:
    path = Path(__file__).resolve().parents[2] / "prompts" / "semantic_intent_actions_system.txt"
    return path.read_text(encoding="utf-8").strip()


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    cleaned = _CODE_FENCE_RE.sub("", cleaned).strip()
    return cleaned


def _parse_json(text: str) -> dict[str, Any] | None:
    cleaned = _strip_code_fence(text)
    if not cleaned:
        return None
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except Exception:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except Exception:
            return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except Exception:
        return None


def _normalize_actions(raw: Any) -> dict[str, list[dict]]:
    actions = dict(DEFAULT_ACTIONS)
    if not isinstance(raw, dict):
        return actions
    for key in actions.keys():
        items = raw.get(key)
        if isinstance(items, list):
            filtered: list[dict] = []
            for item in items:
                if isinstance(item, dict):
                    filtered.append(item)
            actions[key] = filtered
    return actions


def analyze_user_message(text: str, *, brain=None, settings: dict | None = None) -> IntentActionsResult | None:
    if not text or not text.strip():
        return None
    brain = brain or get_brain()
    system_prompt = _load_system_prompt()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Сообщение пользователя:\n{text}"},
    ]

    schema = {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": sorted(list(VALID_INTENTS))},
            "confidence": {"type": "number"},
            "actions": {
                "type": "object",
                "properties": {
                    "save_memory": {"type": "array", "items": {"type": "object"}},
                    "save_preferences": {"type": "array", "items": {"type": "object"}},
                    "create_reminders": {"type": "array", "items": {"type": "object"}},
                    "web_research": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["save_memory", "save_preferences", "create_reminders", "web_research"],
            },
        },
        "required": ["intent", "confidence", "actions"],
    }

    privacy_settings = dict(settings or {})
    privacy = dict(privacy_settings.get("privacy") or {})
    privacy.update({"strict_local": True, "cloud_allowed": False, "auto_cloud_enabled": False})
    privacy_settings["privacy"] = privacy
    llm_ctx = SimpleNamespace(run={}, task={}, plan_step={}, settings=privacy_settings)

    request = LLMRequest(
        purpose="intent_actions",
        task_kind="intent_classification",
        messages=messages,
        context_items=[ContextItem(content=text, source_type="user_prompt", sensitivity="personal")],
        temperature=0.1,
        max_tokens=500,
        json_schema=schema,
    )

    try:
        response = brain.call(request, llm_ctx)
    except Exception:
        return None
    if response.status != "ok":
        return None

    data = _parse_json(response.text or "")
    if not data:
        return None

    intent = data.get("intent") if isinstance(data.get("intent"), str) else None
    if intent not in VALID_INTENTS:
        return None

    confidence = _coerce_float(data.get("confidence"))
    if confidence is None:
        return None

    actions = _normalize_actions(data.get("actions"))

    return IntentActionsResult(intent=intent, confidence=confidence, actions=actions, raw=data)


def _normalize_text(text: str) -> str:
    cleaned = text.strip().lower().replace("ё", "е")
    return re.sub(r"\s+", " ", cleaned)


def _evidence_in_text(evidence: str, text: str) -> bool:
    if not evidence or not text:
        return False
    return _normalize_text(evidence) in _normalize_text(text)


def _ensure_period(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    if stripped[-1] in ".!?":
        return stripped
    return stripped + "."


def _normalize_fact_sentence(value: str, key: str | None = None) -> str:
    value = value.strip()
    if not value:
        return value
    lowered = value.lower()
    if lowered.startswith("пользователь") or lowered.startswith("пользователя"):
        return _ensure_period(value)
    if key:
        key_l = key.lower()
        if "user.name" in key_l or "user.nickname" in key_l:
            return _ensure_period(f"Пользователя зовут {value}")
        if "style" in key_l or "format" in key_l or "preference" in key_l:
            return _ensure_period(f"Пользователь предпочитает {value}")
        if "constraint" in key_l or "prohibit" in key_l or "ban" in key_l:
            return _ensure_period(f"Пользователь запрещает {value}")
    return _ensure_period(f"Пользователь {value}")


def _name_evidence_ok(evidence: str) -> bool:
    return bool(_NAME_EVIDENCE_RE.search(evidence))


def collect_memory_facts(
    actions: dict[str, list[dict]] | None,
    raw_text: str,
    existing_memories: list[dict],
    *,
    limit: int = 5,
    min_confidence: float = 0.85,
    min_len: int = 2,
    max_len: int = 120,
) -> list[str]:
    if not actions:
        return []
    existing_norm = {
        _normalize_text(str(item.get("content", ""))) for item in existing_memories if isinstance(item, dict)
    }
    new_norm: set[str] = set()
    results: list[str] = []

    def _handle(items: list[dict]) -> None:
        nonlocal results
        for item in items:
            if len(results) >= limit:
                return
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            evidence = item.get("evidence")
            confidence = _coerce_float(item.get("confidence"))
            key = item.get("key") if isinstance(item.get("key"), str) else None
            if not isinstance(value, str) or not isinstance(evidence, str):
                continue
            if confidence is None or confidence < min_confidence:
                continue
            value = value.strip()
            evidence = evidence.strip()
            if not value or not evidence:
                continue
            if not _evidence_in_text(evidence, raw_text):
                continue
            if key and ("user.name" in key.lower() or "user.nickname" in key.lower()):
                if not _name_evidence_ok(evidence):
                    continue
            if not (min_len <= len(value) <= max_len):
                continue
            sentence = _normalize_fact_sentence(value, key)
            norm = _normalize_text(sentence)
            if norm in existing_norm or norm in new_norm:
                continue
            new_norm.add(norm)
            results.append(sentence)

    _handle(actions.get("save_memory", []))
    _handle(actions.get("save_preferences", []))

    return results


def extract_web_research(actions: dict[str, list[dict]] | None, *, min_confidence: float = 0.7) -> list[dict]:
    if not actions:
        return []
    results: list[dict] = []
    for item in actions.get("web_research", []) if isinstance(actions.get("web_research"), list) else []:
        if not isinstance(item, dict):
            continue
        query = item.get("query") if isinstance(item.get("query"), str) else None
        confidence = _coerce_float(item.get("confidence"))
        if not query or confidence is None or confidence < min_confidence:
            continue
        sources_target = item.get("sources_target")
        sources_val = None
        if isinstance(sources_target, int) and sources_target > 0:
            sources_val = min(20, sources_target)
        results.append({"query": query.strip(), "sources_target": sources_val, "confidence": confidence, "evidence": item.get("evidence")})
    return results


def extract_reminders(actions: dict[str, list[dict]] | None, *, min_confidence: float = 0.7) -> list[dict]:
    if not actions:
        return []
    results: list[dict] = []
    for item in actions.get("create_reminders", []) if isinstance(actions.get("create_reminders"), list) else []:
        if not isinstance(item, dict):
            continue
        when_text = item.get("when_text") if isinstance(item.get("when_text"), str) else ""
        text = item.get("text") if isinstance(item.get("text"), str) else ""
        confidence = _coerce_float(item.get("confidence"))
        if confidence is None or confidence < min_confidence:
            continue
        evidence = item.get("evidence") if isinstance(item.get("evidence"), str) else None
        results.append({"when_text": when_text.strip(), "text": text.strip(), "confidence": confidence, "evidence": evidence})
    return results
