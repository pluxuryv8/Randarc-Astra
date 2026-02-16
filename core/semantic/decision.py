from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.brain.router import get_brain
from core.brain.types import LLMRequest
from core.llm_routing import ContextItem

INTENT_CHAT = "CHAT"
INTENT_ACT = "ACT"
INTENT_ASK = "ASK_CLARIFY"
VALID_INTENTS = {INTENT_CHAT, INTENT_ACT, INTENT_ASK}

VALID_MEMORY_KINDS = {"user_profile", "assistant_profile", "user_preference", "other"}
VALID_PLAN_HINTS = {
    "CHAT_RESPONSE",
    "CLARIFY_QUESTION",
    "WEB_RESEARCH",
    "BROWSER_RESEARCH_UI",
    "COMPUTER_ACTIONS",
    "DOCUMENT_WRITE",
    "FILE_ORGANIZE",
    "CODE_ASSIST",
    "MEMORY_COMMIT",
    "REMINDER_CREATE",
    "SMOKE_RUN",
}


@dataclass
class SemanticMemoryItem:
    kind: str
    text: str
    evidence: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "text": self.text, "evidence": self.evidence}


@dataclass
class SemanticDecision:
    intent: str
    confidence: float
    memory_item: SemanticMemoryItem | None
    plan_hint: list[str]
    response_style_hint: str | None
    user_visible_note: str | None
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "memory_item": self.memory_item.to_dict() if self.memory_item else None,
            "plan_hint": list(self.plan_hint),
            "response_style_hint": self.response_style_hint,
            "user_visible_note": self.user_visible_note,
        }


class SemanticDecisionError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail or code
        super().__init__(f"{code}: {self.detail}")


def _load_prompt() -> str:
    path = Path(__file__).resolve().parents[2] / "prompts" / "semantic_decision.md"
    return path.read_text(encoding="utf-8").strip()


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": sorted(list(VALID_INTENTS))},
            "confidence": {"type": "number"},
            "memory_item": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": sorted(list(VALID_MEMORY_KINDS))},
                            "text": {"type": "string"},
                            "evidence": {"type": "string"},
                        },
                        "required": ["kind", "text", "evidence"],
                        "additionalProperties": False,
                    },
                ]
            },
            "plan_hint": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(list(VALID_PLAN_HINTS))},
            },
            "response_style_hint": {"type": ["string", "null"]},
            "user_visible_note": {"type": ["string", "null"]},
        },
        "required": ["intent", "confidence", "memory_item", "plan_hint", "response_style_hint", "user_visible_note"],
        "additionalProperties": False,
    }


def _as_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise SemanticDecisionError("semantic_decision_invalid_confidence", "confidence must be number")


def _as_optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SemanticDecisionError("semantic_decision_invalid_field", f"{field} must be string or null")
    normalized = " ".join(value.strip().split())
    return normalized or None


def _parse_memory_item(value: Any, user_text: str) -> SemanticMemoryItem | None:
    if value is None:
        return None
    if isinstance(value, list):
        raise SemanticDecisionError("semantic_decision_memory_item_must_be_object", "memory_item array is forbidden")
    if not isinstance(value, dict):
        raise SemanticDecisionError("semantic_decision_memory_item_invalid", "memory_item must be object or null")

    kind = value.get("kind")
    text = value.get("text")
    evidence = value.get("evidence")

    if kind not in VALID_MEMORY_KINDS:
        raise SemanticDecisionError("semantic_decision_memory_item_invalid_kind", "memory_item.kind is invalid")
    if not isinstance(text, str) or not text.strip():
        raise SemanticDecisionError("semantic_decision_memory_item_invalid_text", "memory_item.text is required")
    if not isinstance(evidence, str) or not evidence.strip():
        raise SemanticDecisionError("semantic_decision_memory_item_invalid_evidence", "memory_item.evidence is required")

    clean_text = " ".join(text.strip().split())
    clean_evidence = evidence.strip()
    if clean_evidence not in user_text:
        raise SemanticDecisionError(
            "semantic_decision_evidence_not_substring",
            "memory_item.evidence must be a direct substring of user message",
        )

    return SemanticMemoryItem(kind=kind, text=clean_text, evidence=clean_evidence)


def _parse_plan_hint(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise SemanticDecisionError("semantic_decision_plan_hint_invalid", "plan_hint must be an array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SemanticDecisionError("semantic_decision_plan_hint_invalid", "plan_hint entries must be strings")
        if item not in VALID_PLAN_HINTS:
            raise SemanticDecisionError("semantic_decision_plan_hint_unknown", f"unknown plan_hint: {item}")
        if item not in result:
            result.append(item)
    return result


def _parse_response(text: str, user_text: str) -> SemanticDecision:
    raw_text = text.strip()
    if not raw_text:
        raise SemanticDecisionError("semantic_decision_empty_response")

    try:
        data = json.loads(raw_text)
    except Exception as exc:  # noqa: BLE001
        raise SemanticDecisionError("semantic_decision_invalid_json", str(exc)) from exc

    if not isinstance(data, dict):
        raise SemanticDecisionError("semantic_decision_invalid_payload", "response must be JSON object")

    intent = data.get("intent")
    if intent not in VALID_INTENTS:
        raise SemanticDecisionError("semantic_decision_invalid_intent", "intent is invalid")

    confidence = _as_float(data.get("confidence"))
    if confidence < 0.0 or confidence > 1.0:
        raise SemanticDecisionError("semantic_decision_invalid_confidence", "confidence must be in [0, 1]")

    memory_item = _parse_memory_item(data.get("memory_item"), user_text)
    plan_hint = _parse_plan_hint(data.get("plan_hint"))
    response_style_hint = _as_optional_text(data.get("response_style_hint"), "response_style_hint")
    user_visible_note = _as_optional_text(data.get("user_visible_note"), "user_visible_note")

    return SemanticDecision(
        intent=intent,
        confidence=confidence,
        memory_item=memory_item,
        plan_hint=plan_hint,
        response_style_hint=response_style_hint,
        user_visible_note=user_visible_note,
        raw=data,
    )


def decide_semantic(
    user_text: str,
    *,
    brain=None,
    run_id: str | None = None,
    settings: dict[str, Any] | None = None,
) -> SemanticDecision:
    text = (user_text or "").strip()
    if not text:
        raise SemanticDecisionError("semantic_decision_empty_input")

    brain = brain or get_brain()
    prompt = _load_prompt()

    privacy_settings = dict(settings or {})
    privacy = dict(privacy_settings.get("privacy") or {})
    privacy.update({"strict_local": True, "cloud_allowed": False, "auto_cloud_enabled": False})
    privacy_settings["privacy"] = privacy
    llm_ctx = SimpleNamespace(run={"id": run_id} if run_id else {}, task={}, plan_step={}, settings=privacy_settings)

    request = LLMRequest(
        purpose="semantic_decision",
        task_kind="intent_classification",
        run_id=run_id,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Сообщение пользователя:\n{text}"},
        ],
        context_items=[ContextItem(content=text, source_type="user_prompt", sensitivity="personal")],
        temperature=0.0,
        max_tokens=600,
        json_schema=_schema(),
    )

    try:
        response = brain.call(request, llm_ctx)
    except Exception as exc:  # noqa: BLE001
        raise SemanticDecisionError("semantic_decision_llm_call_failed", str(exc)) from exc

    if response.status != "ok":
        detail = response.error_type or response.status
        raise SemanticDecisionError("semantic_decision_llm_failed", detail)

    return _parse_response(response.text or "", text)
