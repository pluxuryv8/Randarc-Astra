from __future__ import annotations

from collections import defaultdict
import re

from core.skills.result_types import SkillResult
from memory import store


def _normalize_key(key: str, value: object | None) -> str:
    if isinstance(value, dict):
        entity = value.get("entity")
        field = value.get("field")
        context = value.get("context")
        if entity and field:
            base = f"{entity}.{field}"
            if context:
                base = f"{base}.{context}"
            return _slug(base)
    return _slug(key or "")


def _slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9а-яё]+", "_", text)
    return text.strip("_")


def run(inputs: dict, ctx) -> SkillResult:
    run_id = ctx.run["id"]
    facts = store.list_facts(run_id)

    grouped = defaultdict(list)
    for fact in facts:
        key = _normalize_key(fact.get("key") or "", fact.get("value"))
        value = fact.get("value")
        grouped[key].append({"value": value, "source_ids": fact.get("source_ids") or []})

    events = []
    for key, values in grouped.items():
        distinct = {str(v["value"]) for v in values}
        if len(distinct) > 1:
            events.append(
                {
                    "type": "conflict",
                    "fact_key": key,
                    "group": values,
                    "message": f"Конфликт по ключу {key}",
                }
            )

    return SkillResult(
        what_i_did="Проверены извлечённые факты на конфликты.",
        events=events,
        confidence=0.5 if events else 1.0,
    )
