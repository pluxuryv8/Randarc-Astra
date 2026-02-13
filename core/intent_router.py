from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from core.brain.router import get_brain
from core.brain.types import LLMRequest, LLMResponse
from core.llm_routing import ContextItem
from core.reminders.parser import parse_reminder_text

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
    needs_clarification: bool = False
    act_hint: ActHint | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "questions": list(self.questions),
            "needs_clarification": self.needs_clarification,
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
    "посмотри",
    "выполни",
    "выполнить",
    "найди",
    "проанализируй",
    "проанализировать",
    "анализируй",
    "перепиши",
    "распредели",
    "напиши",
    "отправь",
    "отправить",
    "сделай",
    "сделать",
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
    "доклад",
    "отчет",
    "отчёт",
    "стать",
    "эссе",
    "заметк",
    "obsidian",
    "финанс",
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

_CHAT_PATTERNS = (
    "какие есть",
    "что такое",
    "почему",
    "объясни",
    "мне нравится",
    "мне нравятся",
    "мне грустно",
)

_ACT_PATTERNS = (
    "найди в браузере",
    "найди в интернете",
    "найди в яндексе",
    "найди в гугле",
    "посмотри проект",
    "посмотри код",
    "посмотри окно",
    "перепиши",
    "проанализируй",
    "проанализировать",
)

_AMBIGUOUS_PHRASES = (
    "сделай это",
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
    def __init__(self, *, brain=None, rule_confidence: float = 0.75, llm_confidence: float = 0.6, qa_mode: bool | None = None) -> None:
        self.brain = brain or get_brain()
        self.rule_confidence = rule_confidence
        self.llm_confidence = llm_confidence
        if qa_mode is None:
            qa_mode = os.getenv("ASTRA_QA_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
        self.qa_mode = qa_mode

    def decide(self, text: str) -> IntentDecision:
        normalized = _normalize(text)
        if not normalized:
            return self._build_clarify(["empty_input"])

        decision = self._rule_based(normalized)
        if decision and decision.confidence >= self.rule_confidence:
            return decision
        if decision and decision.intent in {INTENT_ACT, INTENT_CHAT}:
            return decision

        if self.qa_mode:
            return decision or self._build_clarify(["qa_mode"])

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
                needs_clarification=False,
                act_hint=ActHint(target=TARGET_TEXT_ONLY, danger_flags=[], suggested_run_mode="execute_confirm"),
            )

        if _contains_any(text, _REMINDER_TRIGGERS):
            _, _, question = parse_reminder_text(text)
            if question:
                return IntentDecision(
                    intent=INTENT_ACT,
                    confidence=0.74,
                    reasons=["reminder_needs_time"],
                    questions=[question],
                    needs_clarification=True,
                    act_hint=ActHint(target=TARGET_TEXT_ONLY, danger_flags=[], suggested_run_mode="execute_confirm"),
                )
            return IntentDecision(
                intent=INTENT_ACT,
                confidence=0.84,
                reasons=["reminder_trigger"],
                needs_clarification=False,
                act_hint=ActHint(target=TARGET_TEXT_ONLY, danger_flags=[], suggested_run_mode="execute_confirm"),
            )

        has_action_verb = _contains_any(text, _ACTION_VERBS)
        has_action_object = _contains_any(text, _ACTION_OBJECT_HINTS)
        has_computer_context = _contains_any(text, _COMPUTER_CONTEXT)
        has_chat_hint = _contains_any(text, _CHAT_HINTS) or text.endswith("?")
        has_chat_pattern = _contains_any(text, _CHAT_PATTERNS)
        has_act_pattern = _contains_any(text, _ACT_PATTERNS)
        has_browser_find = "найди" in text and _contains_any(text, ("в браузере", "в интернете", "в яндексе", "в гугле"))
        has_doc_request = _contains_any(text, ("доклад", "отчет", "отчёт", "стать", "эссе", "документ"))
        has_url = bool(re.search(r"https?://", text))

        reasons: list[str] = []
        if ambiguous and not has_action_verb and not has_chat_hint and not has_chat_pattern:
            return self._build_clarify(["ambiguous_short"], hint="short")

        explicit_act = has_action_object or has_computer_context or has_url or has_browser_find or has_act_pattern or has_doc_request
        chat_signal = has_chat_hint or has_chat_pattern or text.endswith("?")

        if has_browser_find:
            reasons.append("browser_find")
            danger_flags = sorted(self._detect_danger_flags(text))
            act_hint = self._build_act_hint(text, danger_flags)
            return IntentDecision(intent=INTENT_ACT, confidence=0.9, reasons=reasons, act_hint=act_hint)

        if chat_signal and not explicit_act:
            reasons.append("chat_signal")
            if text.endswith("?"):
                reasons.append("question")
            return IntentDecision(intent=INTENT_CHAT, confidence=0.85, reasons=reasons)

        if explicit_act or has_action_verb:
            reasons.append("action_signal")
            if has_action_object:
                reasons.append("action_object")
            if has_computer_context:
                reasons.append("computer_context")
            if has_doc_request:
                reasons.append("doc_request")
            danger_flags = sorted(self._detect_danger_flags(text))
            act_hint = self._build_act_hint(text, danger_flags)
            needs_clarification = not explicit_act
            questions = self._default_questions() if needs_clarification else []
            return IntentDecision(
                intent=INTENT_ACT,
                confidence=0.9 if not needs_clarification else 0.7,
                reasons=reasons,
                questions=questions,
                needs_clarification=needs_clarification,
                act_hint=act_hint,
            )

        if chat_signal:
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
        return IntentDecision(intent=INTENT_ASK, confidence=0.5, reasons=reasons, questions=questions, needs_clarification=False)

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
            needs_clarification=False,
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
