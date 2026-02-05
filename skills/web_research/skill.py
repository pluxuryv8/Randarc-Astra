from __future__ import annotations

from urllib.parse import urlparse

from core.providers.search_client import build_search_client
from core.skills.result_types import SkillResult, SourceCandidate


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


def run(inputs: dict, ctx) -> SkillResult:
    query = inputs.get("query") or ctx.run.get("query_text", "")
    urls = inputs.get("urls") or []

    sources: list[SourceCandidate] = []
    try:
        client = build_search_client(ctx.settings)
        results = client.search(query, urls)
        for item in results:
            if not item.get("url"):
                continue
            sources.append(
                SourceCandidate(
                    url=item["url"],
                    title=item.get("title"),
                    snippet=item.get("snippet"),
                    domain=_domain(item["url"]),
                    quality="primary" if item.get("snippet") else "unknown",
                )
            )
    except Exception as exc:
        return SkillResult(
            what_i_did="Поиск не удался",
            assumptions=[f"Ошибка поиска: {exc}"],
            confidence=0.0,
        )

    return SkillResult(
        what_i_did="Собраны кандидаты источников",
        sources=sources,
        assumptions=[],
        confidence=0.4 if sources else 0.1,
        next_actions=["Извлечь факты из источников"],
    )
