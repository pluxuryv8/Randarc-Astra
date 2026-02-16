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

MAX_ITEMS = 5
MIN_CONFIDENCE = 0.75
MAX_TEXT_LEN = 160

_TYPE_PREFIX = {
    "identity": "Имя пользователя",
    "preference": "Предпочтение",
    "rule": "Правило",
    "other": "Факт",
}


@dataclass
class NormalizedItem:
    type: str
    text: str
    confidence: float
    evidence: str


def _load_system_prompt() -> str:
    path = Path(__file__).resolve().parents[1] / "prompts" / "memory_normalize_system.txt"
    return path.read_text(encoding="utf-8").strip()


def _parse_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    try:
        data = json.loads(cleaned)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except Exception:
        return None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().replace("ё", "е"))


def _ensure_period(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    if stripped[-1] in ".!?":
        return stripped
    return stripped + "."


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _looks_like_raw_copy(text: str, content: str) -> bool:
    norm_text = _normalize_text(text)
    norm_content = _normalize_text(content)
    if not norm_text or not norm_content:
        return False
    return norm_text == norm_content


def _apply_prefix(item_type: str, text: str) -> str:
    base = text.strip()
    if not base:
        return base
    prefix = _TYPE_PREFIX.get(item_type, "Факт")
    lowered = base.lower()
    if lowered.startswith(prefix.lower()):
        return _ensure_period(base)
    return _ensure_period(f"{prefix}: {base}")


def normalize_memory_texts(
    content: str,
    *,
    draft_items: list[str] | None = None,
    settings: dict | None = None,
    brain=None,
) -> list[str]:
    if not content or not content.strip():
        return []

    brain = brain or get_brain()
    system_prompt = _load_system_prompt()
    draft_block = ""
    if draft_items:
        draft_lines = [f"- {item}" for item in draft_items if isinstance(item, str) and item.strip()]
        if draft_lines:
            draft_block = "\n\nЧерновик фактов (если есть, можно уточнить):\n" + "\n".join(draft_lines)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Сообщение пользователя:\n{content}{draft_block}"},
    ]

    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["identity", "preference", "rule", "other"]},
                        "text": {"type": "string"},
                        "confidence": {"type": "number"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["type", "text", "confidence", "evidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }

    privacy_settings = dict(settings or {})
    privacy = dict(privacy_settings.get("privacy") or {})
    privacy.update({"strict_local": True, "cloud_allowed": False, "auto_cloud_enabled": False})
    privacy_settings["privacy"] = privacy
    llm_ctx = SimpleNamespace(run={}, task={}, plan_step={}, settings=privacy_settings)

    request = LLMRequest(
        purpose="memory_normalize",
        task_kind="chat",
        messages=messages,
        context_items=[ContextItem(content=content, source_type="user_prompt", sensitivity="personal")],
        temperature=0.1,
        max_tokens=500,
        json_schema=schema,
    )

    try:
        response = brain.call(request, llm_ctx)
    except Exception:
        return []
    if response.status != "ok":
        return []

    data = _parse_json(response.text or "")
    if not data:
        return []

    raw_items = data.get("items") if isinstance(data.get("items"), list) else []
    results: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if len(results) >= MAX_ITEMS:
            break
        if not isinstance(item, dict):
            continue
        item_type = item.get("type") if isinstance(item.get("type"), str) else "other"
        text = item.get("text") if isinstance(item.get("text"), str) else ""
        evidence = item.get("evidence") if isinstance(item.get("evidence"), str) else ""
        confidence = _coerce_float(item.get("confidence"))
        if confidence is None or confidence < MIN_CONFIDENCE:
            continue
        text = text.strip()
        evidence = evidence.strip()
        if not text or not evidence:
            continue
        if evidence not in content:
            continue
        normalized = _apply_prefix(item_type, text)
        normalized = _truncate(normalized, MAX_TEXT_LEN)
        if _looks_like_raw_copy(normalized, content):
            continue
        norm_key = _normalize_text(normalized)
        if norm_key in seen:
            continue
        seen.add(norm_key)
        results.append(normalized)

    return results
