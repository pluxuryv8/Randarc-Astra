from __future__ import annotations

import re

ASK_CLARIFY_MEMORY = "Что именно запомнить?"
ASK_CLARIFY_REMINDER_TIME = "Во сколько напомнить? Варианты: через 30 минут / через 1 час / сегодня в 16:00."
ASK_CLARIFY_WEB = "Что именно нужно найти в интернете?"

CONFIRM_DANGER = "Нужно подтверждение: действие может быть опасным. Продолжать?"
DONE = "Готово."
ERROR = "Ошибка. Что уточнить?"

_RUDE_WORDS = (
    "дурак",
    "идиот",
    "дебил",
    "кретин",
    "туп",
    "кринж",
)


def contains_rude_words(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").lower())
    return any(word in normalized for word in _RUDE_WORDS)


def with_name(text: str, name: str | None) -> str:
    if not text:
        return text
    if not name:
        return text
    trimmed = text.strip()
    if not trimmed:
        return text
    if trimmed.lower().startswith(name.lower()):
        return text
    lowered = trimmed[:1].lower() + trimmed[1:] if len(trimmed) > 1 else trimmed.lower()
    return f"{name}, {lowered}"
