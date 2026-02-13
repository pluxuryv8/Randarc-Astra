from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.brain import LLMRequest, get_brain
from core.llm_routing import ContextItem
from core.skills.result_types import FactCandidate, SkillResult
from memory import store


def _load_system_prompt(base_dir: str) -> str:
    prompt_path = Path(base_dir) / "prompts" / "extract_facts_system.txt"
    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except Exception:
        return "Извлеки атомарные факты из сниппетов. Верни JSON с ключом facts[]. Каждый факт: {key, value, confidence, source_id}. Ничего не выдумывай."


def _heuristic_facts(text: str) -> list[tuple[str, Any]]:
    facts: list[tuple[str, Any]] = []
    if not text:
        return facts

    for match in re.finditer(r"([A-ZА-ЯЁ][^.,:]{3,60})\s+(?:is|это)\s+([^.,]{3,120})", text):
        key = match.group(1).strip()
        value = match.group(2).strip()
        facts.append((key, value))

    for match in re.finditer(r"([A-ZА-ЯЁ][^.,:]{3,60})\s*[—-]\s*([^.,]{3,120})", text):
        key = match.group(1).strip()
        value = match.group(2).strip()
        facts.append((key, value))

    for match in re.finditer(r"([A-ZА-ЯЁ][^.,:]{3,60})\s*:\s*([^.,]{3,120})", text):
        key = match.group(1).strip()
        value = match.group(2).strip()
        facts.append((key, value))

    if not facts:
        facts.append(("фрагмент", text.strip()))
    return facts


def _parse_llm_response(resp: dict | str) -> list[dict]:
    if not resp:
        return []
    if isinstance(resp, str):
        content = resp
    elif "choices" in resp:
        content = resp["choices"][0]["message"]["content"]
    else:
        return []
    try:
        parsed = json.loads(content)
    except Exception:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1:
            return []
        parsed = json.loads(content[start : end + 1])
    return parsed.get("facts", [])


def run(inputs: dict, ctx) -> SkillResult:
    run_id = ctx.run["id"]
    sources = store.list_sources(run_id)
    if inputs.get("source_ids"):
        allowed = set(inputs.get("source_ids") or [])
        sources = [s for s in sources if s["id"] in allowed]

    fact_candidates: list[FactCandidate] = []
    assumptions: list[str] = []

    try:
        context_items = [
            ContextItem(
                content={
                    "source_id": s["id"],
                    "title": s.get("title"),
                    "url": s.get("url"),
                    "snippet": s.get("snippet"),
                },
                source_type="web_page_text",
                sensitivity="public",
                provenance=s.get("url") or s["id"],
            )
            for s in sources
            if s.get("snippet")
        ]

        def build_messages(items: list[ContextItem]) -> list[dict[str, Any]]:
            snippets: list[dict[str, Any]] = []
            for item in items:
                data = item.content
                if isinstance(data, dict):
                    snippet = data.get("snippet")
                    if not snippet:
                        continue
                    snippets.append({
                        "source_id": data.get("source_id") or item.provenance,
                        "title": data.get("title"),
                        "url": data.get("url") or item.provenance,
                        "snippet": snippet,
                    })
                else:
                    snippet = str(data)
                    if not snippet:
                        continue
                    snippets.append({
                        "source_id": item.provenance or "",
                        "url": item.provenance,
                        "snippet": snippet,
                    })

            return [
                {
                    "role": "system",
                    "content": _load_system_prompt(ctx.base_dir),
                },
                {"role": "user", "content": json.dumps({"snippets": snippets}, ensure_ascii=False)},
            ]

        request = LLMRequest(
            purpose="extract_facts",
            task_kind="fact_extraction",
            context_items=context_items,
            render_messages=build_messages,
            preferred_model_kind="chat",
            temperature=0.2,
            run_id=ctx.run.get("id"),
            task_id=ctx.task.get("id"),
            step_id=ctx.plan_step.get("id"),
        )
        response = get_brain().call(request, ctx)
        if response.status != "ok":
            raise RuntimeError(response.error_type or "llm_failed")
        facts = _parse_llm_response(response.text)
        for fact in facts:
            if not fact.get("key") or "value" not in fact:
                continue
            fact_candidates.append(
                FactCandidate(
                    key=str(fact.get("key")),
                    value=fact.get("value"),
                    confidence=float(fact.get("confidence") or 0.5),
                    source_ids=[fact.get("source_id")] if fact.get("source_id") else [],
                )
            )
    except Exception as exc:
        assumptions.append(f"Ошибка LLM: {exc}")

    if not fact_candidates:
        for source in sources:
            snippet = source.get("snippet") or ""
            for key, value in _heuristic_facts(snippet):
                fact_candidates.append(
                    FactCandidate(
                        key=key,
                        value=value,
                        confidence=0.3,
                        source_ids=[source["id"]],
                    )
                )

    return SkillResult(
        what_i_did="Извлечены факты из сниппетов источников.",
        facts=fact_candidates,
        assumptions=assumptions,
        confidence=0.4 if fact_candidates else 0.0,
    )
