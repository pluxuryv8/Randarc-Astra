from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from core.semantic.decision import SemanticDecision, SemanticDecisionError, decide_semantic

INTENT_CHAT = "CHAT"
INTENT_ACT = "ACT"
INTENT_ASK = "ASK_CLARIFY"

TARGET_COMPUTER = "COMPUTER"
TARGET_TEXT_ONLY = "TEXT_ONLY"

_DANGER_PATTERNS = {
    "send_message": ("отправ", "сообщени", "email", "почт", "sms", "whatsapp", "telegram", "discord", "message"),
    "delete_file": ("удали", "удалить", "delete", "rm ", "стер", "очисти", "trash", "корзин"),
    "payment": ("оплат", "платеж", "перевод", "куп", "заказ", "payment", "card", "банк"),
    "publish": ("опублику", "выложи", "publish", "deploy", "release", "tweet", "post", "push"),
    "account_settings": ("аккаунт", "profile", "настройк", "settings", "security", "логин"),
    "password": ("парол", "password", "passphrase", "2fa", "код подтверждения"),
}

_COMPUTER_PLAN_KINDS = {
    "BROWSER_RESEARCH_UI",
    "COMPUTER_ACTIONS",
    "DOCUMENT_WRITE",
    "FILE_ORGANIZE",
    "CODE_ASSIST",
    "SMOKE_RUN",
}


@dataclass
class ActHint:
    target: str
    danger_flags: list[str] = field(default_factory=list)
    suggested_run_mode: str = "autopilot_safe"

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "danger_flags": list(self.danger_flags),
            "suggested_run_mode": self.suggested_run_mode,
        }


@dataclass
class IntentDecision:
    intent: str
    confidence: float
    reasons: list[str]
    questions: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    act_hint: ActHint | None = None
    plan_hint: list[str] = field(default_factory=list)
    memory_item: dict[str, str] | None = None
    response_style_hint: str | None = None
    user_visible_note: str | None = None
    decision_path: str = "semantic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "questions": list(self.questions),
            "needs_clarification": self.needs_clarification,
            "act_hint": self.act_hint.to_dict() if self.act_hint else None,
            "plan_hint": list(self.plan_hint),
            "memory_item": dict(self.memory_item) if self.memory_item else None,
            "response_style_hint": self.response_style_hint,
            "user_visible_note": self.user_visible_note,
            "decision_path": self.decision_path,
        }


class IntentRouter:
    def __init__(self, *, brain=None, qa_mode: bool | None = None) -> None:
        self.brain = brain
        if qa_mode is None:
            qa_mode = os.getenv("ASTRA_QA_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
        self.qa_mode = qa_mode

    def decide(self, text: str, *, run_id: str | None = None, settings: dict | None = None) -> IntentDecision:
        raw_text = (text or "").strip()
        if not raw_text:
            return IntentDecision(
                intent=INTENT_ASK,
                confidence=1.0,
                reasons=["empty_input"],
                questions=["Уточни, пожалуйста, запрос."],
                needs_clarification=True,
                decision_path="semantic",
            )

        if self.qa_mode:
            return IntentDecision(
                intent=INTENT_ACT,
                confidence=1.0,
                reasons=["qa_mode"],
                plan_hint=["COMPUTER_ACTIONS"],
                act_hint=ActHint(target=TARGET_COMPUTER, danger_flags=[], suggested_run_mode="autopilot_safe"),
                decision_path="qa_mode",
            )

        semantic = decide_semantic(raw_text, brain=self.brain, run_id=run_id, settings=settings)
        return self._from_semantic(raw_text, semantic)

    def _from_semantic(self, raw_text: str, semantic: SemanticDecision) -> IntentDecision:
        questions: list[str] = []
        needs_clarification = False
        if semantic.intent == INTENT_ASK:
            needs_clarification = True
            if semantic.user_visible_note:
                questions = [semantic.user_visible_note]
            else:
                questions = ["Уточни, пожалуйста, что именно нужно сделать."]

        act_hint: ActHint | None = None
        if semantic.intent == INTENT_ACT:
            danger_flags = self._detect_danger_flags(raw_text)
            target = TARGET_COMPUTER if any(kind in _COMPUTER_PLAN_KINDS for kind in semantic.plan_hint) else TARGET_TEXT_ONLY
            suggested_run_mode = "execute_confirm" if target == TARGET_TEXT_ONLY or danger_flags else "autopilot_safe"
            act_hint = ActHint(target=target, danger_flags=danger_flags, suggested_run_mode=suggested_run_mode)

        memory_item = semantic.memory_item.to_dict() if semantic.memory_item else None
        reasons = ["semantic_decision"]
        if semantic.plan_hint:
            reasons.append("plan_hint")
        if memory_item:
            reasons.append("memory_item")

        return IntentDecision(
            intent=semantic.intent,
            confidence=semantic.confidence,
            reasons=reasons,
            questions=questions,
            needs_clarification=needs_clarification,
            act_hint=act_hint,
            plan_hint=list(semantic.plan_hint),
            memory_item=memory_item,
            response_style_hint=semantic.response_style_hint,
            user_visible_note=semantic.user_visible_note,
            decision_path="semantic",
        )

    def _detect_danger_flags(self, text: str) -> list[str]:
        lowered = (text or "").lower()
        flags: set[str] = set()
        for flag, patterns in _DANGER_PATTERNS.items():
            if any(token in lowered for token in patterns):
                flags.add(flag)
        return sorted(flags)


__all__ = [
    "INTENT_CHAT",
    "INTENT_ACT",
    "INTENT_ASK",
    "TARGET_COMPUTER",
    "TARGET_TEXT_ONLY",
    "ActHint",
    "IntentDecision",
    "IntentRouter",
    "SemanticDecisionError",
]
