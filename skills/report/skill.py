from __future__ import annotations

from pathlib import Path

from core.skills.result_types import ArtifactCandidate, SkillResult
from memory import store


def _render_report(run: dict, sources: list[dict], facts: list[dict], conflicts: list[dict]) -> str:
    lines = []
    lines.append(f"# Отчёт по запуску {run['id']}")
    lines.append("")
    lines.append("## Запрос")
    lines.append(run.get("query_text") or "")
    lines.append("")

    lines.append("## Источники")
    if not sources:
        lines.append("- Не найдено")
    for s in sources:
        title = s.get("title") or s.get("url")
        lines.append(f"- {title} ({s.get('url')})")
        if s.get("snippet"):
            lines.append(f"  - {s['snippet']}")
    lines.append("")

    lines.append("## Факты")
    if not facts:
        lines.append("- Не найдено")
    for f in facts:
        lines.append(f"- **{f.get('key')}**: {f.get('value')} (уверенность: {f.get('confidence')})")
    lines.append("")

    lines.append("## Конфликты")
    if not conflicts:
        lines.append("- Нет")
    for c in conflicts:
        lines.append(f"- {c.get('fact_key')}")
        group = c.get("group") or []
        for entry in group:
            lines.append(f"  - {entry.get('value')} (источники: {entry.get('source_ids')})")
    lines.append("")

    lines.append("## Итог")
    if facts:
        lines.append("- Сводка собрана на основе извлечённых фактов.")
    else:
        lines.append("- Факты не извлечены.")
    lines.append("")

    return "\n".join(lines)


def run(inputs: dict, ctx) -> SkillResult:
    run = ctx.run
    run_id = run["id"]
    sources = store.list_sources(run_id)
    facts = store.list_facts(run_id)
    conflicts = store.list_conflicts(run_id)
    report_md = _render_report(run, sources, facts, conflicts)

    base_dir = Path(ctx.base_dir)
    out_dir = base_dir / "artifacts" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")

    artifacts = [
        ArtifactCandidate(
            type="report_md",
            title="Отчёт",
            content_uri=str(report_path),
            meta={"format": "markdown"},
        )
    ]

    return SkillResult(
        what_i_did="Сформирован markdown-отчёт на основе источников, фактов и конфликтов.",
        artifacts=artifacts,
        confidence=0.6 if facts else 0.3,
    )
