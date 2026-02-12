from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from core.brain.router import get_brain
from core.reminders.parser import parse_reminder_text
from core.brain.types import LLMRequest, LLMResponse
from core.llm_routing import ContextItem

INTENT_CHAT = "CHAT"
INTENT_ACT = "ACT"
INTENT_ASK = "ASK_CLARIFY"

TARGET_COMPUTER = "COMPUTER"
TARGET_TEXT_ONLY = "TEXT_ONLY"

DANGER_FLAGS = {
    "send_message",
    "delete_file",
    "payment",
    "publish",
    "account_settings",
    "password",
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
    act_hint: ActHint | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "questions": list(self.questions),
            "act_hint": self.act_hint.to_dict() if self.act_hint else None,
        }


_ACTION_VERBS = (
    "открой",
    "нажми",
    "кликни",
    "перетащи",
    "перемести",
    "запусти",
    "запускай",
    "проверь",
    "проверить",
    "выполни",
    "выполнить",
    "удали",
    "удалить",
    "создай",
    "создать",
    "переименуй",
    "скачай",
    "установи",
    "включи",
    "выключи",
    "закрой",
    "перейди",
    "отсортируй",
)

_ACTION_OBJECT_HINTS = (
    "файл",
    "папк",
    "плейлист",
    "браузер",
    "сайт",
    "ссылк",
    "url",
    "вкладк",
    "окно",
    "приложени",
    "терминал",
    "консоль",
    "команд",
    "shell",
    "vscode",
    "finder",
    "проводник",
    "документ",
    "таблиц",
    "проект",
    "репозиторий",
)

_COMPUTER_CONTEXT = (
    "на компьютере",
    "на экране",
    "в браузере",
    "в vscode",
    "в терминале",
    "в finder",
    "в проводнике",
    "в приложении",
)

_CHAT_HINTS = (
    "объясни",
    "что такое",
    "расскажи",
    "поговори",
    "подскажи",
    "напиши текст",
    "перефразируй",
    "суммируй",
    "сделай вывод",
    "посоветуй",
)

_AMBIGUOUS_PHRASES = (
    "сделай это",
    "посмотри",
    "это",
    "сделай",
    "помоги",
)

_DANGER_PATTERNS = {
    "send_message": (
        "отправ",
        "сообщени",
        "email",
        "почт",
        "sms",
        "whatsapp",
        "telegram",
        "discord",
        "message",
    ),
    "delete_file": ("удали", "удалить", "delete", "rm ", "стер", "очисти", "trash", "корзин"),
    "payment": ("оплат", "платеж", "перевод", "куп", "заказ", "payment", "card", "банк"),
    "publish": ("опублику", "выложи", "publish", "deploy", "release", "tweet", "post", "push"),
    "account_settings": ("аккаунт", "profile", "настройк", "settings", "security", "логин"),
    "password": ("парол", "password", "passphrase"),
}

_MEMORY_TRIGGERS = ("запомни", "сохрани", "в память", "зафиксируй", "запиши")
_REMINDER_TRIGGERS = ("напомни", "напомнить", "напоминание")

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[\w\-]+", text.lower(), flags=re.UNICODE)


class IntentRouter:
    def __init__(self, *, brain=None, rule_confidence: float = 0.75, llm_confidence: float = 0.6) -> None:
        self.brain = brain or get_brain()
        self.rule_confidence = rule_confidence
        self.llm_confidence = llm_confidence

    def decide(self, text: str) -> IntentDecision:
        normalized = _normalize(text)
        if not normalized:
            return self._build_clarify(["empty_input"])

        decision = self._rule_based(normalized)
        if decision and decision.confidence >= self.rule_confidence:
            return decision
        if decision and decision.intent == INTENT_ASK:
            return decision

        llm_decision = self._llm_classify(normalized)
        if llm_decision and llm_decision.confidence >= self.llm_confidence:
            return llm_decision

        return self._build_clarify(["low_confidence"])

    def _rule_based(self, text: str) -> IntentDecision:
        tokens = _tokenize(text)
        short = len(tokens) <= 2
        ambiguous = short or _contains_any(text, _AMBIGUOUS_PHRASES)

        if _contains_any(text, _MEMORY_TRIGGERS):
            return IntentDecision(
                intent=INTENT_ACT,
                confidence=0.82,
                reasons=["memory_trigger"],
                act_hint=ActHint(target=TARGET_TEXT_ONLY, danger_flags=[], suggested_run_mode="execute_confirm"),
            )

        if _contains_any(text, _REMINDER_TRIGGERS):
            _, _, question = parse_reminder_text(text)
            if question:
                return IntentDecision(intent=INTENT_ASK, confidence=0.7, reasons=["reminder_needs_time"], questions=[question])
            return IntentDecision(
                intent=INTENT_ACT,
                confidence=0.84,
                reasons=["reminder_trigger"],
                act_hint=ActHint(target=TARGET_TEXT_ONLY, danger_flags=[], suggested_run_mode="execute_confirm"),
            )

        has_action_verb = _contains_any(text, _ACTION_VERBS)
        has_action_object = _contains_any(text, _ACTION_OBJECT_HINTS)
        has_computer_context = _contains_any(text, _COMPUTER_CONTEXT)
        has_chat_hint = _contains_any(text, _CHAT_HINTS) or text.endswith("?")
        has_url = bool(re.search(r"https?://", text))

        reasons: list[str] = []
        if ambiguous and not has_action_verb and not has_chat_hint:
            return self._build_clarify(["ambiguous_short"], hint="short")

        is_act = has_action_verb and (has_action_object or has_computer_context or has_url)
        is_chat = has_chat_hint and not has_action_verb

        if is_act and not is_chat:
            reasons.append("action_verbs")
            if has_action_object:
                reasons.append("action_object")
            if has_computer_context:
                reasons.append("computer_context")
            danger_flags = sorted(self._detect_danger_flags(text))
            act_hint = self._build_act_hint(text, danger_flags)
            return IntentDecision(intent=INTENT_ACT, confidence=0.9, reasons=reasons, act_hint=act_hint)

        if is_chat and not is_act:
            reasons.append("chat_hints")
            if text.endswith("?"):
                reasons.append("question")
            return IntentDecision(intent=INTENT_CHAT, confidence=0.85, reasons=reasons)

        if is_act and is_chat:
            reasons.append("conflict_act_chat")
            return IntentDecision(intent=INTENT_ASK, confidence=0.55, reasons=reasons, questions=self._default_questions())

        if has_action_verb and not has_action_object and not has_computer_context:
            reasons.append("action_verb_no_context")
            return IntentDecision(intent=INTENT_ASK, confidence=0.6, reasons=reasons, questions=self._default_questions())

        if has_chat_hint:
            reasons.append("chat_hint_low")
            return IntentDecision(intent=INTENT_CHAT, confidence=0.65, reasons=reasons)

        return self._build_clarify(["no_signal"])

    def _build_act_hint(self, text: str, danger_flags: list[str]) -> ActHint:
        target = TARGET_COMPUTER
        if _contains_any(text, _CHAT_HINTS):
            target = TARGET_TEXT_ONLY
        suggested_run_mode = "execute_confirm" if danger_flags else "autopilot_safe"
        return ActHint(target=target, danger_flags=danger_flags, suggested_run_mode=suggested_run_mode)

    def _default_questions(self) -> list[str]:
        return [
            "Нужно ответить текстом или выполнить действия на компьютере?",
            "Если действия — в каком приложении или месте это сделать?",
        ]

    def _build_clarify(self, reasons: list[str], hint: str | None = None) -> IntentDecision:
        questions = self._default_questions()
        if hint == "short":
            questions = ["Нужно ответить текстом или выполнить действия на компьютере?"]
        return IntentDecision(intent=INTENT_ASK, confidence=0.5, reasons=reasons, questions=questions)

    def _detect_danger_flags(self, text: str) -> set[str]:
        flags: set[str] = set()
        for flag, patterns in _DANGER_PATTERNS.items():
            if any(pat in text for pat in patterns):
                flags.add(flag)
        return flags

    def _llm_classify(self, text: str) -> IntentDecision | None:
        schema = {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": [INTENT_CHAT, INTENT_ACT, INTENT_ASK]},
                "confidence": {"type": "number"},
                "reasons": {"type": "array", "items": {"type": "string"}},
                "questions": {"type": "array", "items": {"type": "string"}},
                "danger_flags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["intent", "confidence"],
        }

        messages = [
            {
                "role": "system",
                "content": "Ты классификатор намерений. Ответь только JSON без пояснений.",
            },
            {
                "role": "user",
                "content": (
                    "Определи intent: CHAT, ACT, ASK_CLARIFY. "
                    "Если неясно, верни ASK_CLARIFY и 1-2 коротких вопроса. "
                    "Выдели danger_flags при опасных действиях (send_message, delete_file, payment, publish, account_settings, password).\n\n"
                    f"Запрос: {text}"
                ),
            },
        ]

        request = LLMRequest(
            purpose="intent_router",
            task_kind="intent_classification",
            messages=messages,
            context_items=[ContextItem(content=text, source_type="user_prompt", sensitivity="personal")],
            temperature=0.0,
            max_tokens=200,
            json_schema=schema,
        )

        try:
            response = self.brain.call(request)
        except Exception:
            return None

        data = self._extract_json(response)
        if not data:
            return None

        intent = data.get("intent")
        if intent not in {INTENT_CHAT, INTENT_ACT, INTENT_ASK}:
            return None

        confidence = float(data.get("confidence", 0.0))
        reasons = data.get("reasons") or ["llm"]
        if isinstance(reasons, str):
            reasons = [reasons]

        questions = data.get("questions") or []
        if isinstance(questions, str):
            questions = [questions]
        questions = [q for q in questions if q][:2]

        danger_flags = set(data.get("danger_flags") or []) | self._detect_danger_flags(text)
        act_hint = None
        if intent == INTENT_ACT:
            act_hint = self._build_act_hint(text, sorted(danger_flags))

        if intent == INTENT_ASK and not questions:
            questions = self._default_questions()[:1]

        return IntentDecision(
            intent=intent,
            confidence=max(0.0, min(confidence, 1.0)),
            reasons=list(reasons),
            questions=questions,
            act_hint=act_hint,
        )

    def _extract_json(self, response: LLMResponse) -> dict[str, Any] | None:
        text = response.text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None
