from __future__ import annotations

import uuid


def _id() -> str:
    return str(uuid.uuid4())


def create_default_plan(query_text: str) -> list[dict]:
    return [
        {
            "id": _id(),
            "step_index": 0,
            "title": "Автопилот: управление компьютером",
            "skill_name": "autopilot_computer",
            "inputs": {"goal": query_text},
            "depends_on": [],
            "status": "created",
        },
        {
            "id": _id(),
            "step_index": 1,
            "title": "Сохранить в памяти",
            "skill_name": "memory_save",
            "inputs": {},
            "depends_on": [0],
            "status": "created",
        },
    ]


def create_plan_for_query(query_text: str) -> list[dict]:
    return create_default_plan(query_text)
