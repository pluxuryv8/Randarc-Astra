from __future__ import annotations

from core.skills.result_types import SkillResult
from memory import store


def run(inputs: dict, ctx) -> SkillResult:
    run_id = ctx.run["id"]
    sources = store.list_sources(run_id)
    facts = store.list_facts(run_id)
    artifacts = store.list_artifacts(run_id)

    events = [
        {
            "message": "Снимок памяти сохранён",
            "payload": {
                "sources": len(sources),
                "facts": len(facts),
                "artifacts": len(artifacts),
            },
        }
    ]

    return SkillResult(
        what_i_did="Результаты запуска записаны в локальную память.",
        events=events,
        confidence=1.0,
    )
