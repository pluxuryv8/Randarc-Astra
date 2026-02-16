from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any

from core.brain.router import get_brain
from core.brain.types import LLMRequest
from core.intent_router import INTENT_ACT, INTENT_ASK, INTENT_CHAT
from core.llm_routing import ContextItem
from core.reminders.parser import parse_reminder_text
from core.semantic.intent_actions import (
    collect_memory_facts,
    extract_reminders,
    extract_web_research,
)
from memory import store

KIND_CHAT_RESPONSE = "CHAT_RESPONSE"
KIND_CLARIFY = "CLARIFY_QUESTION"
KIND_BROWSER_RESEARCH = "BROWSER_RESEARCH_UI"
KIND_WEB_RESEARCH = "WEB_RESEARCH"
KIND_COMPUTER_ACTIONS = "COMPUTER_ACTIONS"
KIND_DOCUMENT_WRITE = "DOCUMENT_WRITE"
KIND_FILE_ORGANIZE = "FILE_ORGANIZE"
KIND_CODE_ASSIST = "CODE_ASSIST"
KIND_MEMORY_COMMIT = "MEMORY_COMMIT"
KIND_REMINDER_CREATE = "REMINDER_CREATE"
KIND_SMOKE_RUN = "SMOKE_RUN"

ALL_KINDS = {
    KIND_CHAT_RESPONSE,
    KIND_CLARIFY,
    KIND_BROWSER_RESEARCH,
    KIND_WEB_RESEARCH,
    KIND_COMPUTER_ACTIONS,
    KIND_DOCUMENT_WRITE,
    KIND_FILE_ORGANIZE,
    KIND_CODE_ASSIST,
    KIND_MEMORY_COMMIT,
    KIND_REMINDER_CREATE,
    KIND_SMOKE_RUN,
}

KIND_TO_SKILL = {
    KIND_CHAT_RESPONSE: "report",
    KIND_CLARIFY: "report",
    KIND_BROWSER_RESEARCH: "autopilot_computer",
    KIND_WEB_RESEARCH: "web_research",
    KIND_COMPUTER_ACTIONS: "autopilot_computer",
    KIND_DOCUMENT_WRITE: "autopilot_computer",
    KIND_FILE_ORGANIZE: "autopilot_computer",
    KIND_CODE_ASSIST: "autopilot_computer",
    KIND_MEMORY_COMMIT: "memory_save",
    KIND_REMINDER_CREATE: "reminder_create",
    KIND_SMOKE_RUN: "smoke_run",
}

DANGER_PATTERNS = {
    "send_message": ("отправ", "сообщени", "email", "почт", "sms", "whatsapp", "telegram", "discord", "message"),
    "delete_file": ("удали", "удалить", "delete", "rm ", "стер", "очисти", "trash", "корзин"),
    "payment": ("оплат", "платеж", "перевод", "куп", "заказ", "payment", "card", "банк"),
    "publish": ("опублику", "выложи", "publish", "deploy", "release", "tweet", "post", "push"),
    "account_settings": ("аккаунт", "profile", "настройк", "settings", "security", "логин"),
    "password": ("парол", "password", "passphrase", "код подтверждения", "2fa", "one-time"),
}

MEMORY_TRIGGERS = (
    "сохрани в память",
    "запиши себе",
    "запомни",
    "сохрани",
    "в память",
    "зафиксируй",
    "запиши",
)
REMINDER_TRIGGERS = (
    "поставь напоминание",
    "сделай напоминание",
    "напомни",
    "напомнить",
    "напоминание",
)

SEMANTIC_FACTS_LIMIT = 5


def _is_qa_mode(meta: dict | None = None) -> bool:
    if meta and meta.get("qa_mode"):
        return True
    return os.getenv("ASTRA_QA_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _legacy_detectors_enabled() -> bool:
    return os.getenv("ASTRA_LEGACY_DETECTORS", "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class PlanStep:
    id: str
    step_index: int
    title: str
    kind: str
    skill_name: str
    inputs: dict[str, Any]
    success_criteria: str
    danger_flags: list[str]
    requires_approval: bool
    artifacts_expected: list[str]
    depends_on: list[int]
    status: str = "created"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "step_index": self.step_index,
            "title": self.title,
            "kind": self.kind,
            "skill_name": self.skill_name,
            "inputs": self.inputs,
            "success_criteria": self.success_criteria,
            "danger_flags": self.danger_flags,
            "requires_approval": self.requires_approval,
            "artifacts_expected": self.artifacts_expected,
            "depends_on": self.depends_on,
            "status": self.status,
        }


def _id() -> str:
    return str(uuid.uuid4())


def _normalize(text: str) -> str:
    normalized = text.strip().lower().replace("ё", "е")
    return re.sub(r"\s+", " ", normalized)


def _get_semantic_actions(meta: dict | None) -> dict[str, list[dict]] | None:
    if not meta:
        return None
    actions = meta.get("semantic_actions")
    return actions if isinstance(actions, dict) else None


def _semantic_used(meta: dict | None) -> bool:
    if not meta:
        return False
    return bool(meta.get("semantic_used"))


def _safe_list_memories() -> list[dict]:
    try:
        return store.list_user_memories(limit=200)
    except Exception:
        return []


def _is_smoke_query(text: str) -> bool:
    normalized = _normalize(text)
    return normalized.startswith("s_smoke_1") or normalized.startswith("__smoke__") or "s_smoke_1" in normalized


def _build_smoke_plan(query_text: str) -> list[PlanStep]:
    steps = [
        _step(
            0,
            "Smoke: наблюдение и безопасные действия",
            KIND_SMOKE_RUN,
            {"scenario_id": "S_SMOKE_1"},
            "Скриншоты получены и проверено изменение экрана",
        ),
        _step(
            1,
            "Демонстрация safety: удалить test.txt на рабочем столе",
            KIND_COMPUTER_ACTIONS,
            _autopilot_inputs(
                "Удалить файл test.txt на рабочем столе (демо безопасности, требуется подтверждение)",
                ["Если файл отсутствует — остановиться и запросить подтверждение"],
            ),
            "Запрошено подтверждение на удаление файла",
            danger_flags=["delete_file"],
            depends_on=[0],
        ),
    ]
    return steps


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _detect_danger_flags(text: str) -> list[str]:
    flags: set[str] = set()
    for flag, patterns in DANGER_PATTERNS.items():
        if any(pat in text for pat in patterns):
            flags.add(flag)
    return sorted(flags)


def _sanitize_danger_flags(flags: list[str]) -> list[str]:
    allowed = set(DANGER_PATTERNS.keys())
    return [flag for flag in flags if flag in allowed]


def _needs_memory_commit(text: str) -> bool:
    return _contains_any(_normalize(text), MEMORY_TRIGGERS)


def _needs_reminder(text: str) -> bool:
    return _contains_any(_normalize(text), REMINDER_TRIGGERS)


def _extract_memory_payload(text: str) -> dict[str, Any]:
    lowered = text.lower()
    match_pos = None
    match_token = None
    for token in MEMORY_TRIGGERS:
        pos = lowered.find(token)
        if pos != -1 and (
            match_pos is None
            or pos < match_pos
            or (pos == match_pos and match_token is not None and len(token) > len(match_token))
        ):
            match_pos = pos
            match_token = token
    content = text
    if match_pos is not None and match_token is not None:
        content = text[match_pos + len(match_token) :]
    content = re.sub(r"^[\\s,:;.!?\\-—]+", "", content).strip()
    if not content:
        content = re.sub(r"\\b(" + "|".join(map(re.escape, MEMORY_TRIGGERS)) + r")\\b", "", text, flags=re.IGNORECASE).strip()
    if not content:
        content = text.strip()
    title = content.splitlines()[0] if content else "Память пользователя"
    if len(title) > 60:
        title = title[:57] + "..."
    return {"content": content, "title": title, "tags": []}


def _extract_reminder_payload(text: str) -> dict[str, Any]:
    due_at, reminder_text, _ = parse_reminder_text(text)
    if not due_at or not reminder_text:
        return {}
    return {"due_at": due_at, "text": reminder_text}


def _append_semantic_memory_step(raw_text: str, steps: list[PlanStep], actions: dict[str, list[dict]] | None) -> list[PlanStep]:
    if not actions:
        return steps
    existing = _safe_list_memories()
    facts = collect_memory_facts(actions, raw_text, existing, limit=SEMANTIC_FACTS_LIMIT)
    if not facts:
        return steps
    payload = {"content": raw_text.strip(), "facts": facts, "origin": "auto"}
    index = len(steps)
    steps.append(
        _step(
            index,
            "Сохранить факты о пользователе",
            KIND_MEMORY_COMMIT,
            payload,
            "Факты сохранены в памяти",
            depends_on=[index - 1] if index > 0 else [],
            artifacts_expected=["memory"],
        )
    )
    return steps


def _plan_browser_research_for_query(query: str, sources_target: int | None, start_index: int = 0) -> list[PlanStep]:
    sources_count = sources_target or 3
    steps: list[PlanStep] = []
    steps.append(
        _step(
            start_index,
            "Открыть браузер",
            KIND_BROWSER_RESEARCH,
            _autopilot_inputs("Открой браузер и подготовься к поиску"),
            "Открыт браузер и видна строка поиска",
        )
    )
    steps.append(
        _step(
            start_index + 1,
            "Найти источники",
            KIND_BROWSER_RESEARCH,
            _autopilot_inputs(f"Найди {sources_count} релевантных источника(ов) по запросу: {query}"),
            f"Открыты минимум {sources_count} источника",
            depends_on=[start_index],
            artifacts_expected=["sources"],
        )
    )
    steps.append(
        _step(
            start_index + 2,
            "Сформировать краткую выжимку",
            KIND_DOCUMENT_WRITE,
            _autopilot_inputs("Сформируй краткую выжимку по найденным источникам"),
            "Есть краткое резюме по источникам",
            depends_on=[start_index + 1],
            artifacts_expected=["summary"],
        )
    )
    return steps


def _plan_web_research_for_query(query: str, sources_target: int | None, start_index: int = 0) -> list[PlanStep]:
    sources_count = sources_target if isinstance(sources_target, int) and sources_target > 0 else 2
    max_sources = max(2, min(20, sources_count * 2))
    max_pages = max(2, min(max_sources, sources_count + 2))
    return [
        _step(
            start_index,
            "Провести веб-ресёрч и собрать источники",
            KIND_WEB_RESEARCH,
            {
                "query": query,
                "mode": "deep",
                "max_sources_total": max_sources,
                "max_pages_fetch": max_pages,
            },
            f"Сформирован ответ минимум с {sources_count} источниками",
            artifacts_expected=["sources", "web_research_answer_md"],
        )
    ]


def _normalize_relative_time(text: str) -> str:
    normalized = re.sub(r"\bчерез\s+час\b", "через 1 час", text, flags=re.IGNORECASE)
    normalized = re.sub(r"\bчерез\s+полчаса\b", "через 30 минут", normalized, flags=re.IGNORECASE)
    return normalized


def _build_steps_from_semantic(raw_text: str, actions: dict[str, list[dict]] | None) -> list[PlanStep]:
    if not actions:
        return []
    steps: list[PlanStep] = []
    reminders = extract_reminders(actions)
    for item in reminders:
        composed = " ".join(part for part in [item.get("when_text") or "", item.get("text") or ""] if part).strip()
        source_text = _normalize_relative_time(composed or raw_text)
        due_at, reminder_text, _ = parse_reminder_text(source_text)
        if not due_at or not reminder_text:
            continue
        steps.append(
            _step(
                len(steps),
                "Создать напоминание",
                KIND_REMINDER_CREATE,
                {"due_at": due_at, "text": reminder_text},
                "Напоминание добавлено",
                artifacts_expected=["reminder"],
            )
        )

    web_items = extract_web_research(actions)
    if web_items:
        item = web_items[0]
        query = item.get("query") or raw_text
        sources_target = item.get("sources_target") if isinstance(item.get("sources_target"), int) else None
        start_index = len(steps)
        steps.extend(_plan_web_research_for_query(query, sources_target, start_index=start_index))

    return steps


def _step(
    index: int,
    title: str,
    kind: str,
    inputs: dict[str, Any] | None,
    success_criteria: str,
    danger_flags: list[str] | None = None,
    artifacts_expected: list[str] | None = None,
    depends_on: list[int] | None = None,
) -> PlanStep:
    danger_flags = danger_flags or []
    requires_approval = bool(danger_flags)
    return PlanStep(
        id=_id(),
        step_index=index,
        title=title,
        kind=kind,
        skill_name=KIND_TO_SKILL.get(kind, "autopilot_computer"),
        inputs=inputs or {},
        success_criteria=success_criteria,
        danger_flags=danger_flags,
        requires_approval=requires_approval,
        artifacts_expected=artifacts_expected or [],
        depends_on=depends_on or [],
    )


def _autopilot_inputs(goal: str, hints: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"goal": goal}
    if hints:
        payload["hints"] = hints
    return payload


def _plan_playlist(text: str) -> list[PlanStep] | None:
    if "плейлист" not in text and "playlist" not in text:
        return None
    if not any(token in text for token in ("музык", "music", "yandex", "яндекс", "spotify", "apple")):
        return None

    steps = []
    steps.append(
        _step(
            0,
            "Открыть сервис музыки в браузере",
            KIND_BROWSER_RESEARCH,
            _autopilot_inputs(
                "Открой сервис музыки в браузере",
                ["URL: https://music.yandex.ru", "Нужен экран плейлистов"],
            ),
            "В браузере открыт сервис музыки и видна главная страница",
        )
    )
    steps.append(
        _step(
            1,
            "Создать новый плейлист",
            KIND_COMPUTER_ACTIONS,
            _autopilot_inputs("Создай новый плейлист и задай название"),
            "Появился новый плейлист с заданным названием",
            artifacts_expected=["playlist"],
            depends_on=[0],
        )
    )
    steps.append(
        _step(
            2,
            "Добавить треки в плейлист",
            KIND_COMPUTER_ACTIONS,
            _autopilot_inputs("Добавь треки в плейлист согласно запросу пользователя"),
            "В плейлисте отображается список добавленных треков",
            depends_on=[1],
        )
    )
    steps.append(
        _step(
            3,
            "Проверить плейлист",
            KIND_COMPUTER_ACTIONS,
            _autopilot_inputs("Проверь плейлист и его содержимое"),
            "Название плейлиста и количество треков совпадают с запросом",
            depends_on=[2],
        )
    )
    return steps


def _plan_sort_desktop(text: str) -> list[PlanStep] | None:
    if "иконк" not in text and "ярлык" not in text:
        return None
    if "рабоч" not in text and "desktop" not in text:
        return None

    steps = []
    steps.append(
        _step(
            0,
            "Открыть рабочий стол",
            KIND_FILE_ORGANIZE,
            _autopilot_inputs("Открой рабочий стол"),
            "На экране виден рабочий стол",
        )
    )
    steps.append(
        _step(
            1,
            "Сгруппировать иконки по категориям",
            KIND_FILE_ORGANIZE,
            _autopilot_inputs("Сгруппируй иконки по категориям"),
            "Иконки сгруппированы по папкам/типам",
            depends_on=[0],
        )
    )
    steps.append(
        _step(
            2,
            "Проверить порядок",
            KIND_FILE_ORGANIZE,
            _autopilot_inputs("Проверь, что иконки отсортированы и упорядочены"),
            "На рабочем столе нет хаотичного расположения иконок",
            depends_on=[1],
        )
    )
    return steps


def _plan_vscode_review(text: str) -> list[PlanStep] | None:
    if "vscode" not in text and "vs code" not in text and "код" not in text:
        return None
    if "ошиб" not in text and "error" not in text and "problem" not in text:
        return None

    steps = []
    steps.append(
        _step(
            0,
            "Открыть VSCode",
            KIND_COMPUTER_ACTIONS,
            _autopilot_inputs("Открой VSCode"),
            "VSCode открыт и виден стартовый экран",
        )
    )
    steps.append(
        _step(
            1,
            "Открыть проект",
            KIND_CODE_ASSIST,
            _autopilot_inputs("Открой проект в VSCode"),
            "Проект открыт и видна структура файлов",
            depends_on=[0],
        )
    )
    steps.append(
        _step(
            2,
            "Проверить панель Problems",
            KIND_CODE_ASSIST,
            _autopilot_inputs("Открой панель Problems и собери ошибки"),
            "В панели Problems отображаются ошибки/предупреждения",
            depends_on=[1],
        )
    )
    steps.append(
        _step(
            3,
            "Сформировать краткий список ошибок",
            KIND_CODE_ASSIST,
            _autopilot_inputs("Сформируй список ошибок и предупреждений"),
            "Список ошибок сформирован для пользователя",
            depends_on=[2],
            artifacts_expected=["error_summary"],
        )
    )
    return steps


def _plan_code_project(text: str) -> list[PlanStep] | None:
    if not any(token in text for token in ("vscode", "vs code", "код", "проект", "репозиторий")):
        return None
    if not any(token in text for token in ("бот", "проект", "прилож", "сервис", "скрипт")):
        return None

    steps = []
    steps.append(
        _step(
            0,
            "Открыть VSCode",
            KIND_COMPUTER_ACTIONS,
            _autopilot_inputs("Открой VSCode"),
            "VSCode открыт и виден стартовый экран",
        )
    )
    steps.append(
        _step(
            1,
            "Создать или открыть рабочий проект",
            KIND_CODE_ASSIST,
            _autopilot_inputs("Создай или открой рабочий проект в VSCode"),
            "Проект открыт и видна структура файлов",
            depends_on=[0],
        )
    )
    steps.append(
        _step(
            2,
            "Сформировать план структуры проекта",
            KIND_CODE_ASSIST,
            _autopilot_inputs("Сформируй структуру файлов и основные модули проекта"),
            "Определена структура проекта и ключевые файлы",
            depends_on=[1],
            artifacts_expected=["project_structure"],
        )
    )
    steps.append(
        _step(
            3,
            "Реализовать основной каркас",
            KIND_CODE_ASSIST,
            _autopilot_inputs("Реализуй каркас и основные файлы проекта"),
            "Каркас проекта создан и файлы на месте",
            depends_on=[2],
            artifacts_expected=["source_code"],
        )
    )
    return steps


def _plan_obsidian_migrate(text: str) -> list[PlanStep] | None:
    if "obsidian" not in text and "заметк" not in text:
        return None
    if not any(token in text for token in ("перепиш", "структур", "перенес", "организ")):
        return None

    steps = []
    steps.append(
        _step(
            0,
            "Открыть Obsidian",
            KIND_COMPUTER_ACTIONS,
            _autopilot_inputs("Открой Obsidian"),
            "Obsidian открыт и виден список заметок",
        )
    )
    steps.append(
        _step(
            1,
            "Создать структуру заметок",
            KIND_COMPUTER_ACTIONS,
            _autopilot_inputs("Создай структуру папок и заголовков под новые заметки"),
            "Структура заметок создана",
            depends_on=[0],
        )
    )
    steps.append(
        _step(
            2,
            "Перенести и структурировать заметки",
            KIND_COMPUTER_ACTIONS,
            _autopilot_inputs("Перенеси заметки и структурируй их по разделам"),
            "Заметки перенесены и структурированы",
            depends_on=[1],
            artifacts_expected=["obsidian_notes"],
        )
    )
    return steps


def _plan_browser_research(text: str) -> list[PlanStep] | None:
    has_search_verb = any(token in text for token in ("найди", "поищи", "загугли"))
    has_search_noun = any(token in text for token in ("поиск", "источ"))
    has_context = any(token in text for token in ("браузер", "интернет", "гугл", "яндекс", "google", "yandex", "источ"))
    if not (has_search_verb or (has_search_noun and has_context)):
        return None

    steps = []
    steps.append(
        _step(
            0,
            "Открыть браузер",
            KIND_BROWSER_RESEARCH,
            _autopilot_inputs("Открой браузер и подготовься к поиску"),
            "Открыт браузер и видна строка поиска",
        )
    )
    steps.append(
        _step(
            1,
            "Найти источники",
            KIND_BROWSER_RESEARCH,
            _autopilot_inputs("Найди 3 релевантных источника по запросу пользователя"),
            "Открыты минимум 3 источника",
            depends_on=[0],
            artifacts_expected=["sources"],
        )
    )
    steps.append(
        _step(
            2,
            "Сформировать краткую выжимку",
            KIND_DOCUMENT_WRITE,
            _autopilot_inputs("Сформируй краткую выжимку по найденным источникам"),
            "Есть краткое резюме по источникам",
            depends_on=[1],
            artifacts_expected=["summary"],
        )
    )
    return steps


def _plan_document_write(text: str) -> list[PlanStep] | None:
    if not any(token in text for token in ("доклад", "стать", "эссе", "отчёт", "отчет")):
        return None

    steps = []
    steps.append(
        _step(
            0,
            "Сформировать структуру документа",
            KIND_DOCUMENT_WRITE,
            _autopilot_inputs("Составь план документа"),
            "Есть план документа с разделами",
        )
    )
    steps.append(
        _step(
            1,
            "Написать черновик",
            KIND_DOCUMENT_WRITE,
            _autopilot_inputs("Напиши черновик документа по плану"),
            "Черновик документа готов и соответствует объёму",
            depends_on=[0],
            artifacts_expected=["draft"],
        )
    )
    steps.append(
        _step(
            2,
            "Проверить формат и финализировать",
            KIND_DOCUMENT_WRITE,
            _autopilot_inputs("Проверь объём и финализируй документ"),
            "Документ оформлен и готов к выдаче",
            depends_on=[1],
            artifacts_expected=["document"],
        )
    )
    return steps


def _plan_generic_act(text: str) -> list[PlanStep]:
    steps = []
    steps.append(
        _step(
            0,
            "Подготовить рабочее окружение",
            KIND_COMPUTER_ACTIONS,
            _autopilot_inputs(f"Подготовь окружение для задачи: {text}"),
            "Открыто нужное приложение или страница",
        )
    )
    steps.append(
        _step(
            1,
            "Выполнить ключевые действия",
            KIND_COMPUTER_ACTIONS,
            _autopilot_inputs(f"Выполни основную часть задачи: {text}"),
            "Действия выполнены и виден ожидаемый результат",
            depends_on=[0],
        )
    )
    steps.append(
        _step(
            2,
            "Проверить результат",
            KIND_COMPUTER_ACTIONS,
            _autopilot_inputs(f"Проверь результат задачи: {text}"),
            "Результат совпадает с запросом пользователя",
            depends_on=[1],
        )
    )
    return steps


def _apply_danger_flags(steps: list[PlanStep], flags: list[str]) -> None:
    if not flags:
        return
    for step in steps:
        if step.kind in {KIND_COMPUTER_ACTIONS, KIND_BROWSER_RESEARCH, KIND_FILE_ORGANIZE, KIND_CODE_ASSIST, KIND_DOCUMENT_WRITE}:
            step.danger_flags = flags
            step.requires_approval = True


def _sanitize_plan_inputs(steps: list[PlanStep], fallback_goal: str) -> None:
    allowed = {"goal", "hints", "max_cycles", "max_actions", "screenshot_width", "quality", "loop_delay_ms"}
    for step in steps:
        if step.skill_name == "autopilot_computer":
            raw = step.inputs or {}
            goal = raw.get("goal") if isinstance(raw.get("goal"), str) else None
            hints = raw.get("hints") if isinstance(raw.get("hints"), list) else []
            extra = [f"{k}: {v}" for k, v in raw.items() if k not in allowed]
            if extra:
                hints = list(hints) + extra
            if not goal:
                goal = step.title or fallback_goal
            cleaned: dict[str, Any] = {"goal": goal}
            if hints:
                cleaned["hints"] = hints
            for key in ("max_cycles", "max_actions", "screenshot_width", "quality", "loop_delay_ms"):
                value = raw.get(key)
                if isinstance(value, int):
                    cleaned[key] = value
            step.inputs = cleaned
        elif step.skill_name == "memory_save":
            raw = step.inputs or {}
            content = raw.get("content") if isinstance(raw.get("content"), str) else ""
            title = raw.get("title") if isinstance(raw.get("title"), str) else ""
            tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
            facts = raw.get("facts") if isinstance(raw.get("facts"), list) else []
            memory_payload = raw.get("memory_payload") if isinstance(raw.get("memory_payload"), dict) else None
            origin = raw.get("origin") if isinstance(raw.get("origin"), str) else ""
            if not content:
                content = fallback_goal.strip() if isinstance(fallback_goal, str) else ""
            if not content:
                content = step.title or "Запись пользователя"
            cleaned: dict[str, Any] = {"content": content}
            if title:
                cleaned["title"] = title
            if tags:
                cleaned["tags"] = tags
            if facts:
                cleaned["facts"] = [str(item).strip() for item in facts if isinstance(item, (str, int, float)) and str(item).strip()]
            if memory_payload:
                cleaned["memory_payload"] = memory_payload
            if origin:
                cleaned["origin"] = origin
            step.inputs = cleaned
        elif step.skill_name == "report":
            step.inputs = {}


def _add_password_step_if_needed(text: str, steps: list[PlanStep]) -> None:
    if "password" not in text and "парол" not in text and "код подтверждения" not in text and "2fa" not in text:
        return
    index = len(steps)
    steps.append(
        _step(
            index,
            "Попросить пользователя ввести пароль вручную",
            KIND_CLARIFY,
            {},
            "Пользователь ввёл пароль вручную",
            danger_flags=["password"],
            depends_on=[index - 1] if index > 0 else [],
        )
    )


def _llm_plan(text: str) -> list[PlanStep] | None:
    if _is_qa_mode():
        return None
    brain = get_brain()

    schema = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "kind": {"type": "string", "enum": sorted(list(ALL_KINDS))},
                        "inputs": {"type": "object"},
                        "success_criteria": {"type": "string"},
                        "danger_flags": {"type": "array", "items": {"type": "string"}},
                        "requires_approval": {"type": "boolean"},
                        "artifacts_expected": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["title", "kind", "success_criteria"],
                },
            }
        },
        "required": ["steps"],
    }

    messages = [
        {
            "role": "system",
            "content": (
                "Ты планировщик задач для ассистента на компьютере. "
                "Верни JSON с ключом steps. "
                "Шаги должны быть 2-8, без shell. "
                "Укажи kind из списка, success_criteria и при необходимости danger_flags."
            ),
        },
        {
            "role": "user",
            "content": (
                "Запрос пользователя:\n"
                f"{text}\n\n"
                "Сформируй план шагов как JSON: {steps: [...]}."
            ),
        },
    ]

    request = LLMRequest(
        purpose="planner_v1",
        task_kind="planning",
        messages=messages,
        context_items=[ContextItem(content=text, source_type="user_prompt", sensitivity="personal")],
        temperature=0.2,
        max_tokens=700,
        json_schema=schema,
    )

    response = brain.call(request)
    if response.status != "ok":
        return None

    raw = response.text.strip()
    try:
        data = json.loads(raw)
    except Exception:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except Exception:
            return None

    steps_raw = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps_raw, list) or not steps_raw:
        return None

    steps: list[PlanStep] = []
    for idx, item in enumerate(steps_raw[:8]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        kind = item.get("kind")
        if not title or kind not in ALL_KINDS:
            continue
        if kind == "SHELL":
            continue
        success_criteria = str(item.get("success_criteria", "")) or "Шаг выполнен"
        danger_flags = item.get("danger_flags") or []
        if not isinstance(danger_flags, list):
            danger_flags = []
        inputs = item.get("inputs") if isinstance(item.get("inputs"), dict) else {}
        artifacts_expected = item.get("artifacts_expected") if isinstance(item.get("artifacts_expected"), list) else []
        steps.append(
            _step(
                idx,
                title,
                kind,
                inputs,
                success_criteria,
                danger_flags=danger_flags,
                artifacts_expected=artifacts_expected,
                depends_on=[idx - 1] if idx > 0 else [],
            )
        )

    return steps or None


def _build_steps_from_text(
    text_norm: str,
    raw_text: str,
    *,
    allow_llm: bool = True,
    allow_memory: bool = True,
    allow_reminder: bool = True,
    allow_web: bool = True,
) -> list[PlanStep]:
    # Legacy detector path is disabled by default; semantic plan_hint is the main path.
    if not _legacy_detectors_enabled():
        return []

    if allow_reminder and _needs_reminder(text_norm):
        payload = _extract_reminder_payload(raw_text)
        if payload:
            steps = [
                _step(
                    0,
                    "Создать напоминание",
                    KIND_REMINDER_CREATE,
                    payload,
                    "Напоминание добавлено",
                    artifacts_expected=["reminder"],
                )
            ]
            return steps

    if allow_memory and any(text_norm.startswith(trigger) for trigger in MEMORY_TRIGGERS):
        steps: list[PlanStep] = []
        return _append_memory_step_if_needed(raw_text, steps)

    plan = (
        _plan_playlist(text_norm)
        or _plan_sort_desktop(text_norm)
        or _plan_vscode_review(text_norm)
        or _plan_code_project(text_norm)
        or _plan_obsidian_migrate(text_norm)
        or (_plan_browser_research(text_norm) if allow_web else None)
        or _plan_document_write(text_norm)
    )
    if not plan:
        if len(text_norm.split()) <= 4:
            plan = _plan_generic_act(raw_text)
        else:
            plan = (_llm_plan(raw_text) if allow_llm else None) or _plan_generic_act(raw_text)

    danger_flags = _detect_danger_flags(text_norm)
    _apply_danger_flags(plan, danger_flags)
    for step in plan:
        step.danger_flags = _sanitize_danger_flags(step.danger_flags)
        step.requires_approval = bool(step.danger_flags)
    _add_password_step_if_needed(text_norm, plan)
    _sanitize_plan_inputs(plan, raw_text)

    return plan


def _append_memory_step_if_needed(text: str, steps: list[PlanStep]) -> list[PlanStep]:
    if not _needs_memory_commit(text):
        return steps
    payload = _extract_memory_payload(text)
    index = len(steps)
    steps.append(
        _step(
            index,
            "Сохранить в память",
            KIND_MEMORY_COMMIT,
            payload,
            "Запись сохранена в памяти",
            depends_on=[index - 1] if index > 0 else [],
            artifacts_expected=["memory"],
        )
    )
    return steps


def _prepend_clarify_step(steps: list[PlanStep], questions: list[str]) -> list[PlanStep]:
    if not questions:
        return steps
    clarify = _step(
        0,
        "Уточнить детали у пользователя",
        KIND_CLARIFY,
        {"questions": questions},
        "Получены уточнения от пользователя",
    )
    new_steps = [clarify]
    for step in steps:
        step.step_index += 1
        if step.depends_on:
            step.depends_on = [idx + 1 for idx in step.depends_on]
        new_steps.append(step)
    return new_steps


def _get_plan_hint(meta: dict | None) -> list[str]:
    if not isinstance(meta, dict):
        return []
    raw = meta.get("plan_hint")
    if not isinstance(raw, list):
        return []
    hints: list[str] = []
    for item in raw:
        if isinstance(item, str) and item in ALL_KINDS and item not in hints:
            hints.append(item)
    return hints


def _memory_payload_from_meta(query_text: str, meta: dict | None) -> dict[str, Any]:
    interpretation = meta.get("memory_interpretation") if isinstance(meta, dict) and isinstance(meta.get("memory_interpretation"), dict) else None
    if interpretation and interpretation.get("should_store") is True:
        summary = interpretation.get("summary")
        if isinstance(summary, str) and summary.strip():
            payload = {
                "content": query_text.strip(),
                "origin": "auto",
                "memory_payload": {
                    "title": interpretation.get("title") if isinstance(interpretation.get("title"), str) else "Профиль пользователя",
                    "summary": summary.strip(),
                    "confidence": interpretation.get("confidence"),
                    "facts": interpretation.get("facts") if isinstance(interpretation.get("facts"), list) else [],
                    "preferences": interpretation.get("preferences")
                    if isinstance(interpretation.get("preferences"), list)
                    else [],
                    "possible_facts": interpretation.get("possible_facts")
                    if isinstance(interpretation.get("possible_facts"), list)
                    else [],
                },
            }
            return payload

    memory_item = meta.get("memory_item") if isinstance(meta, dict) and isinstance(meta.get("memory_item"), dict) else None
    text = memory_item.get("text") if isinstance(memory_item, dict) else None
    if isinstance(text, str) and text.strip():
        return {"content": query_text.strip(), "facts": [text.strip()], "origin": "auto"}
    raise RuntimeError("planner_memory_item_missing")


def _generic_step_for_kind(kind: str, query_text: str, index: int) -> PlanStep:
    title_map = {
        KIND_COMPUTER_ACTIONS: "Выполнить действия на компьютере",
        KIND_DOCUMENT_WRITE: "Подготовить документ",
        KIND_FILE_ORGANIZE: "Организовать файлы",
        KIND_CODE_ASSIST: "Помочь с кодом",
    }
    success_map = {
        KIND_COMPUTER_ACTIONS: "Действия выполнены по запросу пользователя",
        KIND_DOCUMENT_WRITE: "Документ подготовлен по запросу пользователя",
        KIND_FILE_ORGANIZE: "Файлы организованы по запросу пользователя",
        KIND_CODE_ASSIST: "Задача по коду выполнена",
    }
    goal = query_text.strip() or "Выполнить задачу пользователя"
    return _step(
        index,
        title_map.get(kind, "Выполнить задачу"),
        kind,
        _autopilot_inputs(goal),
        success_map.get(kind, "Шаг выполнен"),
        depends_on=[index - 1] if index > 0 else [],
    )


def _build_steps_from_plan_hint(query_text: str, meta: dict | None) -> list[PlanStep]:
    hints = _get_plan_hint(meta)
    interpretation = meta.get("memory_interpretation") if isinstance(meta, dict) and isinstance(meta.get("memory_interpretation"), dict) else None
    if interpretation and interpretation.get("should_store") is True and KIND_MEMORY_COMMIT not in hints:
        hints.append(KIND_MEMORY_COMMIT)
    if not hints:
        hints = [KIND_COMPUTER_ACTIONS]

    steps: list[PlanStep] = []
    for kind in hints:
        index = len(steps)
        if kind == KIND_CHAT_RESPONSE:
            steps.append(
                _step(
                    index,
                    "Ответить пользователю текстом",
                    KIND_CHAT_RESPONSE,
                    {},
                    "Сформирован текстовый ответ пользователю",
                    depends_on=[index - 1] if index > 0 else [],
                    artifacts_expected=["chat_response"],
                )
            )
            continue

        if kind == KIND_MEMORY_COMMIT:
            steps.append(
                _step(
                    index,
                    "Сохранить в память",
                    KIND_MEMORY_COMMIT,
                    _memory_payload_from_meta(query_text, meta),
                    "Запись сохранена в памяти",
                    depends_on=[index - 1] if index > 0 else [],
                    artifacts_expected=["memory"],
                )
            )
            continue

        if kind == KIND_REMINDER_CREATE:
            payload = _extract_reminder_payload(query_text)
            if not payload:
                raise RuntimeError("planner_reminder_payload_missing")
            steps.append(
                _step(
                    index,
                    "Создать напоминание",
                    KIND_REMINDER_CREATE,
                    payload,
                    "Напоминание добавлено",
                    depends_on=[index - 1] if index > 0 else [],
                    artifacts_expected=["reminder"],
                )
            )
            continue

        if kind == KIND_BROWSER_RESEARCH:
            steps.extend(_plan_browser_research_for_query(query_text, None, start_index=index))
            continue

        if kind == KIND_WEB_RESEARCH:
            steps.extend(_plan_web_research_for_query(query_text, None, start_index=index))
            continue

        if kind == KIND_CLARIFY:
            steps.append(
                _step(
                    index,
                    "Уточнить детали у пользователя",
                    KIND_CLARIFY,
                    {"questions": ["Уточни, пожалуйста, детали запроса."]},
                    "Получены уточнения от пользователя",
                    depends_on=[index - 1] if index > 0 else [],
                )
            )
            continue

        if kind == KIND_SMOKE_RUN:
            smoke_steps = _build_smoke_plan(query_text)
            for smoke_step in smoke_steps:
                smoke_step.step_index = len(steps)
                smoke_step.depends_on = [smoke_step.step_index - 1] if smoke_step.step_index > 0 else []
                steps.append(smoke_step)
            continue

        steps.append(_generic_step_for_kind(kind, query_text, index))

    return steps


def create_plan_for_run(run: dict) -> list[dict]:
    query_text = run.get("query_text", "")
    meta = run.get("meta") or {}
    intent = meta.get("intent")

    if _is_smoke_query(query_text):
        return [step.to_dict() for step in _build_smoke_plan(query_text)]

    if intent == INTENT_ASK:
        return []

    if intent == INTENT_CHAT:
        steps = [
            _step(
                0,
                "Ответить пользователю текстом",
                KIND_CHAT_RESPONSE,
                {},
                "Сформирован текстовый ответ пользователю",
                artifacts_expected=["chat_response"],
            )
        ]
        return [step.to_dict() for step in steps]

    hint_steps = _build_steps_from_plan_hint(query_text, meta)
    plan_hints = _get_plan_hint(meta)
    if _legacy_detectors_enabled() and not plan_hints:
        text_norm = _normalize(query_text)
        legacy_steps = _build_steps_from_text(text_norm, query_text)
        steps = legacy_steps or hint_steps
    else:
        steps = hint_steps

    raw_flags = meta.get("danger_flags") if isinstance(meta.get("danger_flags"), list) else None
    danger_flags = _sanitize_danger_flags([str(flag) for flag in raw_flags]) if raw_flags is not None else _detect_danger_flags(_normalize(query_text))
    _apply_danger_flags(steps, danger_flags)
    for step in steps:
        step.danger_flags = _sanitize_danger_flags(step.danger_flags)
        step.requires_approval = bool(step.danger_flags)
    _sanitize_plan_inputs(steps, query_text)

    if meta.get("needs_clarification") and meta.get("intent_questions"):
        steps = _prepend_clarify_step(steps, list(meta.get("intent_questions") or []))
    return [step.to_dict() for step in steps]


def create_plan_for_query(query_text: str) -> list[dict]:
    run = {"query_text": query_text, "meta": {"intent": INTENT_ACT}}
    return create_plan_for_run(run)
