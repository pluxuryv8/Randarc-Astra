from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jsonschema import validate as jsonschema_validate

from core.brain import LLMRequest, get_brain
from core.llm_routing import ContextItem
from core.providers.search_client import StubSearchClient, build_search_client
from core.providers.web_extract import extract_main_text
from core.providers.web_fetch import fetch_url
from core.skills.result_types import ArtifactCandidate, SkillResult, SourceCandidate

MODE_CANDIDATES = "candidates"
MODE_DEEP = "deep"

DEFAULT_MAX_ROUNDS = 3
DEFAULT_MAX_SOURCES_TOTAL = 12
DEFAULT_MAX_PAGES_FETCH = 6

DEPTH_BRIEF = "brief"
DEPTH_NORMAL = "normal"
DEPTH_DEEP = "deep"
VALID_DEPTHS = {DEPTH_BRIEF, DEPTH_NORMAL, DEPTH_DEEP}

_HIGH_TRUST_DOMAINS = (
    ".gov",
    ".edu",
    "wikipedia.org",
    "wikidata.org",
    "docs.",
    "developer.",
)

_DEEP_HINT_TOKENS = (
    "найди",
    "узнай",
    "проверь",
    "источник",
    "источники",
    "что известно",
    "research",
    "find",
    "check",
)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _normalize_query(value: Any) -> str:
    return str(value or "").strip()


def _normalize_urls(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    dedup: list[str] = []
    seen: set[str] = set()
    for item in value:
        url = str(item or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        dedup.append(url)
    return dedup


def _coerce_positive_int(value: Any, default: int) -> int:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        if parsed > 0:
            return parsed
    return default


def _looks_like_deep_request(query: str) -> bool:
    lowered = query.lower()
    return any(token in lowered for token in _DEEP_HINT_TOKENS)


def _resolve_mode(raw_mode: Any, query: str) -> str:
    mode = str(raw_mode or "").strip().lower()
    if mode in {MODE_CANDIDATES, MODE_DEEP}:
        return mode
    if mode:
        raise RuntimeError(f"unsupported_mode:{mode}")
    return MODE_DEEP if _looks_like_deep_request(query) else MODE_CANDIDATES


def _resolve_depth(raw_depth: Any, query: str) -> str:
    depth = str(raw_depth or "").strip().lower()
    if depth in VALID_DEPTHS:
        return depth
    lowered = query.lower()
    if "кратко" in lowered or "short" in lowered:
        return DEPTH_BRIEF
    if "подробно" in lowered or "детально" in lowered or "глубоко" in lowered or "deep" in lowered:
        return DEPTH_DEEP
    return DEPTH_NORMAL


def _resolve_style_hint(inputs: dict[str, Any], ctx) -> str | None:
    explicit = inputs.get("style_hint")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    run_meta = ctx.run.get("meta") if isinstance(ctx.run.get("meta"), dict) else {}
    meta_hint = run_meta.get("response_style_hint")
    if isinstance(meta_hint, str) and meta_hint.strip():
        return meta_hint.strip()

    if isinstance(ctx.settings, dict):
        settings_hint = ctx.settings.get("response_style_hint") or ctx.settings.get("style_hint")
        if isinstance(settings_hint, str) and settings_hint.strip():
            return settings_hint.strip()
    return None


def _canonical_url(url: str) -> str:
    normalized = url.strip()
    return normalized[:-1] if normalized.endswith("/") else normalized


def _candidate_from_result(item: dict[str, Any]) -> dict[str, Any] | None:
    url = str(item.get("url") or "").strip()
    if not url:
        return None
    return {
        "url": _canonical_url(url),
        "title": item.get("title"),
        "snippet": item.get("snippet"),
        "domain": _domain(url),
    }


def _candidate_score(candidate: dict[str, Any]) -> int:
    score = 0
    domain = str(candidate.get("domain") or "")
    if any(token in domain for token in _HIGH_TRUST_DOMAINS):
        score += 3
    if candidate.get("title"):
        score += 1
    if candidate.get("snippet"):
        score += 1
    return score


def _rank_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(candidates, key=lambda item: (_candidate_score(item), len(str(item.get("snippet") or ""))), reverse=True)


def _pick_fetch_targets(candidates: list[dict[str, Any]], already_used: set[str], limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    pool = [item for item in candidates if item["url"] not in already_used]
    selected: list[dict[str, Any]] = []
    used_domains: set[str] = set()

    for item in pool:
        domain = item.get("domain") or ""
        if domain and domain in used_domains:
            continue
        selected.append(item)
        if domain:
            used_domains.add(domain)
        if len(selected) >= limit:
            return selected

    for item in pool:
        if item in selected:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _prompt_path(base_dir: str, filename: str) -> Path:
    return Path(base_dir) / "prompts" / filename


def _load_prompt(base_dir: str, filename: str) -> str:
    path = _prompt_path(base_dir, filename)
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"prompt_read_failed:{filename}") from exc


def _llm_json_schema_judge() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["ENOUGH", "NOT_ENOUGH"]},
            "score": {"type": "number"},
            "why": {"type": "string"},
            "next_query": {"type": ["string", "null"]},
            "missing_topics": {"type": "array", "items": {"type": "string"}},
            "need_sources": {"type": "integer"},
            "used_urls": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["decision", "score", "why", "next_query", "missing_topics", "need_sources", "used_urls"],
        "additionalProperties": False,
    }


def _llm_json_schema_answer() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "answer_markdown": {"type": "string"},
            "used_urls": {"type": "array", "items": {"type": "string"}},
            "unknowns": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer_markdown", "used_urls", "unknowns"],
        "additionalProperties": False,
    }


def _call_llm_json(ctx, *, prompt_name: str, payload: dict[str, Any], schema: dict[str, Any], temperature: float) -> dict[str, Any]:
    system_prompt = _load_prompt(ctx.base_dir, prompt_name)
    user_payload = json.dumps(payload, ensure_ascii=False)
    request = LLMRequest(
        purpose="web_research",
        task_kind="web_research",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ],
        context_items=[ContextItem(content=user_payload, source_type="web_page_text", sensitivity="public")],
        preferred_model_kind="chat",
        temperature=temperature,
        max_tokens=1200,
        run_id=ctx.run.get("id"),
        task_id=ctx.task.get("id"),
        step_id=ctx.plan_step.get("id"),
        json_schema=schema,
    )
    response = get_brain().call(request, ctx)
    if response.status != "ok":
        raise RuntimeError(f"llm_failed:{response.error_type or response.status}")
    try:
        parsed = json.loads((response.text or "").strip())
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("invalid_llm_json") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("invalid_llm_json")
    try:
        jsonschema_validate(instance=parsed, schema=schema)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("invalid_llm_json_schema") from exc
    return parsed


def _judge_research(
    ctx,
    *,
    query: str,
    round_index: int,
    depth: str,
    style_hint: str | None,
    evidence_pack: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence_summary = [
        {"url": item["url"], "title": item.get("title"), "domain": item.get("domain")}
        for item in evidence_pack
    ]
    payload = {
        "query": query,
        "round": round_index,
        "depth": depth,
        "style_hint": style_hint,
        "evidence_summary": evidence_summary,
        "evidence_pack": evidence_pack,
    }
    return _call_llm_json(
        ctx,
        prompt_name="web_research_judge.txt",
        payload=payload,
        schema=_llm_json_schema_judge(),
        temperature=0.2,
    )


def _compose_answer(
    ctx,
    *,
    query: str,
    depth: str,
    style_hint: str | None,
    evidence_pack: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "query": query,
        "depth": depth,
        "style_hint": style_hint,
        "evidence_pack": evidence_pack,
    }
    return _call_llm_json(
        ctx,
        prompt_name="web_research_answer.txt",
        payload=payload,
        schema=_llm_json_schema_answer(),
        temperature=0.3,
    )


def _source_cache_dir(ctx, run_id: str) -> Path:
    out_dir = Path(ctx.base_dir) / "artifacts" / run_id / "sources"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _cache_file_path(ctx, run_id: str, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return _source_cache_dir(ctx, run_id) / f"{digest}.json"


def _normalize_plain_text(text: str, max_chars: int = 25_000) -> str:
    compact = " ".join((text or "").split())
    if len(compact) > max_chars:
        compact = compact[:max_chars].rstrip() + "..."
    return compact


def _fetch_and_extract_cached(
    ctx,
    *,
    run_id: str,
    candidate: dict[str, Any],
    timeout_s: int = 15,
    max_bytes: int = 2_000_000,
) -> dict[str, Any]:
    url = candidate["url"]
    path = _cache_file_path(ctx, run_id, url)
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                return cached
        except Exception:
            pass

    fetched = fetch_url(url, timeout_s=timeout_s, max_bytes=max_bytes)
    extracted_text = ""
    if not fetched.get("error"):
        if fetched.get("html"):
            extracted_text = extract_main_text(str(fetched.get("html") or ""))
        elif fetched.get("text"):
            extracted_text = _normalize_plain_text(str(fetched.get("text") or ""))
        else:
            fetched["error"] = "empty_body"

    payload = {
        "url": url,
        "title": candidate.get("title"),
        "domain": candidate.get("domain") or _domain(url),
        "snippet": candidate.get("snippet"),
        "status_code": fetched.get("status_code"),
        "final_url": fetched.get("final_url") or url,
        "content_type": fetched.get("content_type"),
        "html": fetched.get("html") or "",
        "text": fetched.get("text") or "",
        "extracted_text": extracted_text,
        "error": fetched.get("error"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def _evidence_pack(evidence_map: dict[str, dict[str, Any]], *, max_items: int = 10) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in list(evidence_map.values())[:max_items]:
        items.append(
            {
                "url": entry["url"],
                "title": entry.get("title"),
                "domain": entry.get("domain"),
                "snippet": entry.get("snippet"),
                "text_excerpt": str(entry.get("extracted_text") or "")[:2500],
            }
        )
    return items


def _source_from_evidence(entry: dict[str, Any]) -> SourceCandidate:
    return SourceCandidate(
        url=entry["url"],
        title=entry.get("title"),
        snippet=entry.get("snippet"),
        domain=entry.get("domain"),
        quality="primary" if entry.get("extracted_text") else "unknown",
    )


def _write_answer_artifact(
    ctx,
    *,
    run_id: str,
    answer_markdown: str,
    depth: str,
    rounds: int,
    sources_used: int,
) -> ArtifactCandidate:
    out_dir = Path(ctx.base_dir) / "artifacts" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "web_research_answer.md"
    path.write_text(answer_markdown, encoding="utf-8")
    return ArtifactCandidate(
        type="web_research_answer_md",
        title="Web Research Answer",
        content_uri=str(path),
        meta={"depth": depth, "rounds": rounds, "sources_used": sources_used},
    )


def _confidence(score: Any, sources_count: int) -> float:
    if isinstance(score, (int, float)):
        value = float(score)
        if value < 0:
            return 0.0
        if value > 1:
            return 1.0
        return value
    if sources_count >= 3:
        return 0.8
    if sources_count >= 2:
        return 0.5
    return 0.2


def _deep_failed(
    rounds: int,
    pages_read: int,
    assumptions: list[str],
    code: str,
    *,
    events: list[dict[str, Any]] | None = None,
) -> SkillResult:
    details = list(assumptions)
    details.append(code)
    return SkillResult(
        what_i_did=f"Проведён web research: прочитано {pages_read} страниц, раундов {rounds}",
        assumptions=details,
        confidence=0.0,
        events=list(events or []),
    )


def _progress_event(message: str, *, current: int, total: int, reason_code: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "reason_code": reason_code,
        "progress": {"current": max(0, current), "total": max(1, total), "unit": "round"},
    }
    if isinstance(extra, dict):
        payload.update(extra)
    return {"type": "task_progress", "message": message, "progress": payload["progress"], **payload}


def _query_tokens(query: str) -> list[str]:
    tokens = [token.strip() for token in query.lower().replace("ё", "е").split() if token.strip()]
    return [token for token in tokens if len(token) >= 4][:12]


def _heuristic_judge(query: str, evidence_pack: list[dict[str, Any]]) -> dict[str, Any]:
    if not evidence_pack:
        return {
            "decision": "NOT_ENOUGH",
            "score": 0.0,
            "why": "no_evidence",
            "next_query": query,
            "missing_topics": ["sources"],
            "need_sources": 2,
            "used_urls": [],
        }

    tokens = _query_tokens(query)
    covered = 0
    for item in evidence_pack:
        excerpt = str(item.get("text_excerpt") or "").lower()
        if not excerpt:
            continue
        if not tokens:
            covered += 1
            continue
        if any(token in excerpt for token in tokens):
            covered += 1

    score = min(1.0, covered / max(1, len(evidence_pack)))
    enough_sources = len(evidence_pack) >= 2
    decision = "ENOUGH" if enough_sources and score >= 0.45 else "NOT_ENOUGH"
    missing = []
    if not enough_sources:
        missing.append("sources")
    if score < 0.45:
        missing.append("topic_coverage")
    return {
        "decision": decision,
        "score": score,
        "why": "heuristic_fallback",
        "next_query": query if decision == "NOT_ENOUGH" else None,
        "missing_topics": missing,
        "need_sources": max(0, 2 - len(evidence_pack)),
        "used_urls": [str(item.get("url")) for item in evidence_pack if isinstance(item.get("url"), str)],
    }


def _compose_answer_fallback(
    *,
    query: str,
    evidence_map: dict[str, dict[str, Any]],
    used_urls: list[str] | None = None,
) -> dict[str, Any]:
    urls = [url for url in (used_urls or []) if url in evidence_map]
    if not urls:
        urls = list(evidence_map.keys())[:3]
    lines = [f"Краткий итог по запросу: {query}", "", "Что найдено:"]
    for index, url in enumerate(urls, start=1):
        entry = evidence_map.get(url) or {}
        title = str(entry.get("title") or "").strip() or url
        excerpt = " ".join(str(entry.get("extracted_text") or "").split())
        if len(excerpt) > 220:
            excerpt = excerpt[:220].rstrip() + "..."
        if not excerpt:
            excerpt = "Текст страницы доступен частично."
        lines.append(f"{index}. {title}: {excerpt}")
    lines.append("")
    lines.append("Источники:")
    for index, url in enumerate(urls, start=1):
        lines.append(f"[{index}] {url}")
    return {
        "answer_markdown": "\n".join(lines).strip(),
        "used_urls": urls,
        "unknowns": ["fallback_answer_without_llm"],
    }


def _run_candidates_mode(query: str, urls: list[str], ctx) -> SkillResult:
    sources: list[SourceCandidate] = []
    try:
        client = build_search_client(ctx.settings)
        results = client.search(query, urls)
        for item in results:
            candidate = _candidate_from_result(item if isinstance(item, dict) else {})
            if not candidate:
                continue
            sources.append(
                SourceCandidate(
                    url=candidate["url"],
                    title=candidate.get("title"),
                    snippet=candidate.get("snippet"),
                    domain=candidate.get("domain"),
                    quality="primary" if candidate.get("snippet") else "unknown",
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


def _run_deep_mode(
    query: str,
    urls: list[str],
    *,
    depth: str,
    style_hint: str | None,
    max_rounds: int,
    max_sources_total: int,
    max_pages_fetch: int,
    ctx,
) -> SkillResult:
    if not query and not urls:
        return _deep_failed(0, 0, [], "invalid_query")

    try:
        client = build_search_client(ctx.settings)
    except Exception as exc:
        return _deep_failed(0, 0, [], f"search_client_failed:{exc}")

    if not urls and isinstance(client, StubSearchClient):
        return _deep_failed(0, 0, [], "deep_mode_requires_non_stub_provider")

    run_id = str(ctx.run.get("id") or "unknown")
    candidate_index: dict[str, dict[str, Any]] = {}
    evidence_map: dict[str, dict[str, Any]] = {}
    assumptions: list[str] = []
    progress_events: list[dict[str, Any]] = []
    current_query = query

    progress_events.append(
        _progress_event(
            "Запущен deep web research",
            current=0,
            total=max_rounds,
            reason_code="deep_started",
            extra={"query": current_query},
        )
    )

    for round_index in range(1, max_rounds + 1):
        progress_events.append(
            _progress_event(
                f"Раунд {round_index}/{max_rounds}: поиск источников",
                current=round_index,
                total=max_rounds,
                reason_code="search_round_started",
                extra={"query": current_query},
            )
        )
        if urls:
            results = [{"url": url, "title": None, "snippet": None} for url in urls]
        else:
            try:
                results = client.search(current_query)
            except Exception as exc:
                return _deep_failed(
                    round_index,
                    len(evidence_map),
                    assumptions,
                    f"search_failed:{exc}",
                    events=progress_events,
                )

        progress_events.append(
            _progress_event(
                f"Найдено кандидатов: {len(results)}",
                current=round_index,
                total=max_rounds,
                reason_code="search_results",
                extra={"results_count": len(results)},
            )
        )

        for item in results:
            if not isinstance(item, dict):
                continue
            candidate = _candidate_from_result(item)
            if not candidate:
                continue
            if candidate["url"] in candidate_index:
                continue
            if len(candidate_index) >= max_sources_total * 4:
                break
            candidate_index[candidate["url"]] = candidate

        ranked = _rank_candidates(list(candidate_index.values()))
        remaining_budget = min(max_pages_fetch, max_sources_total) - len(evidence_map)
        targets = _pick_fetch_targets(ranked, set(evidence_map.keys()), remaining_budget)

        fetched_this_round = 0
        for candidate in targets:
            progress_events.append(
                _progress_event(
                    "Загружаю источник",
                    current=round_index,
                    total=max_rounds,
                    reason_code="source_fetch_started",
                    extra={"url": candidate["url"]},
                )
            )
            page = _fetch_and_extract_cached(ctx, run_id=run_id, candidate=candidate)
            if page.get("error"):
                assumptions.append(f"{candidate['url']}: {page['error']}")
                progress_events.append(
                    _progress_event(
                        "Источник недоступен",
                        current=round_index,
                        total=max_rounds,
                        reason_code="source_fetch_failed",
                        extra={"url": candidate["url"], "error": page.get("error")},
                    )
                )
                continue
            extracted_text = str(page.get("extracted_text") or "").strip()
            if not extracted_text:
                assumptions.append(f"{candidate['url']}: empty_extracted_text")
                progress_events.append(
                    _progress_event(
                        "Текст не извлечён",
                        current=round_index,
                        total=max_rounds,
                        reason_code="extract_empty",
                        extra={"url": candidate["url"]},
                    )
                )
                continue

            evidence_map[candidate["url"]] = {
                "url": candidate["url"],
                "title": candidate.get("title"),
                "domain": candidate.get("domain"),
                "snippet": candidate.get("snippet"),
                "extracted_text": extracted_text,
                "final_url": page.get("final_url") or candidate["url"],
            }
            fetched_this_round += 1
            progress_events.append(
                _progress_event(
                    "Источник извлечён",
                    current=round_index,
                    total=max_rounds,
                    reason_code="source_extracted",
                    extra={"url": candidate["url"], "domain": candidate.get("domain")},
                )
            )
            if len(evidence_map) >= max_sources_total:
                break

        if fetched_this_round == 0:
            if evidence_map:
                fallback_payload = _compose_answer_fallback(query=current_query or query, evidence_map=evidence_map)
                used_urls = [url for url in fallback_payload.get("used_urls", []) if isinstance(url, str) and url in evidence_map]
                sources = [_source_from_evidence(evidence_map[url]) for url in used_urls]
                artifact = _write_answer_artifact(
                    ctx,
                    run_id=run_id,
                    answer_markdown=str(fallback_payload.get("answer_markdown") or "").strip(),
                    depth=depth,
                    rounds=round_index,
                    sources_used=len(sources),
                )
                assumptions.append("no_pages_fetched")
                assumptions.append("answer_fallback:reuse_existing_evidence")
                return SkillResult(
                    what_i_did=f"Проведён web research: прочитано {len(evidence_map)} страниц, раундов {round_index}",
                    sources=sources,
                    assumptions=assumptions,
                    confidence=0.3 if sources else 0.1,
                    artifacts=[artifact],
                    events=progress_events,
                )
            return _deep_failed(
                round_index,
                len(evidence_map),
                assumptions,
                "no_pages_fetched",
                events=progress_events,
            )

        pack = _evidence_pack(evidence_map)
        judge_fallback_used = False
        try:
            judge = _judge_research(
                ctx,
                query=current_query,
                round_index=round_index,
                depth=depth,
                style_hint=style_hint,
                evidence_pack=pack,
            )
        except RuntimeError as exc:
            judge_fallback_used = True
            assumptions.append(f"judge_fallback:{exc}")
            judge = _heuristic_judge(current_query, pack)
            progress_events.append(
                _progress_event(
                    "LLM judge недоступен, использую эвристику",
                    current=round_index,
                    total=max_rounds,
                    reason_code="judge_fallback",
                    extra={"error": str(exc)},
                )
            )

        decision = str(judge.get("decision") or "").upper()
        if decision not in {"ENOUGH", "NOT_ENOUGH"}:
            invalid_decision = decision or "empty"
            judge_fallback_used = True
            assumptions.append(f"judge_fallback:invalid_decision:{invalid_decision}")
            judge = _heuristic_judge(current_query, pack)
            decision = str(judge.get("decision") or "").upper()
            progress_events.append(
                _progress_event(
                    "LLM judge вернул некорректное решение, использую эвристику",
                    current=round_index,
                    total=max_rounds,
                    reason_code="judge_fallback",
                    extra={"error": f"invalid_decision:{invalid_decision}"},
                )
            )
        progress_events.append(
            _progress_event(
                f"Оценка покрытия: {decision}",
                current=round_index,
                total=max_rounds,
                reason_code="judge_decision",
                extra={"decision": decision, "score": judge.get("score")},
            )
        )
        if decision == "ENOUGH":
            answer_fallback_used = False
            try:
                answer_payload = _compose_answer(
                    ctx,
                    query=current_query,
                    depth=depth,
                    style_hint=style_hint,
                    evidence_pack=pack,
                )
            except RuntimeError as exc:
                answer_fallback_used = True
                assumptions.append(f"answer_fallback:{exc}")
                answer_payload = _compose_answer_fallback(query=current_query, evidence_map=evidence_map)
                progress_events.append(
                    _progress_event(
                        "LLM ответа недоступен, собран fallback-ответ",
                        current=round_index,
                        total=max_rounds,
                        reason_code="answer_fallback",
                        extra={"error": str(exc)},
                    )
                )

            answer_markdown = str(answer_payload.get("answer_markdown") or "").strip()
            if not answer_markdown:
                answer_payload = _compose_answer_fallback(query=current_query, evidence_map=evidence_map)
                answer_markdown = str(answer_payload.get("answer_markdown") or "").strip()
                assumptions.append("answer_fallback:empty_answer_markdown")

            used_urls = [url for url in answer_payload.get("used_urls", []) if isinstance(url, str) and url in evidence_map]
            if not used_urls:
                used_urls = [url for url in judge.get("used_urls", []) if isinstance(url, str) and url in evidence_map]
            if not used_urls:
                used_urls = list(evidence_map.keys())[:3]

            unknowns = [item for item in answer_payload.get("unknowns", []) if isinstance(item, str) and item.strip()]
            assumptions.extend([f"unknown:{item.strip()}" for item in unknowns])

            sources = [_source_from_evidence(evidence_map[url]) for url in used_urls]
            artifact = _write_answer_artifact(
                ctx,
                run_id=run_id,
                answer_markdown=answer_markdown,
                depth=depth,
                rounds=round_index,
                sources_used=len(sources),
            )
            return SkillResult(
                what_i_did=f"Проведён web research: прочитано {len(evidence_map)} страниц, раундов {round_index}",
                sources=sources,
                assumptions=assumptions,
                confidence=_confidence(0.65 if answer_fallback_used or judge_fallback_used else judge.get("score"), len(sources)),
                artifacts=[artifact],
                events=progress_events,
            )

        if decision != "NOT_ENOUGH":
            fallback_payload = _compose_answer_fallback(query=current_query, evidence_map=evidence_map)
            used_urls = [url for url in fallback_payload.get("used_urls", []) if isinstance(url, str) and url in evidence_map]
            sources = [_source_from_evidence(evidence_map[url]) for url in used_urls]
            artifact = _write_answer_artifact(
                ctx,
                run_id=run_id,
                answer_markdown=str(fallback_payload.get("answer_markdown") or "").strip(),
                depth=depth,
                rounds=round_index,
                sources_used=len(sources),
            )
            assumptions.append("answer_fallback:invalid_judge_decision")
            return SkillResult(
                what_i_did=f"Проведён web research: прочитано {len(evidence_map)} страниц, раундов {round_index}",
                sources=sources,
                assumptions=assumptions,
                confidence=0.35 if sources else 0.1,
                artifacts=[artifact],
                events=progress_events,
            )

        next_query = str(judge.get("next_query") or "").strip()
        if urls:
            assumptions.append("explicit_urls_mode_no_extra_queries")
            continue
        if not next_query:
            fallback_payload = _compose_answer_fallback(query=current_query, evidence_map=evidence_map)
            used_urls = [url for url in fallback_payload.get("used_urls", []) if isinstance(url, str) and url in evidence_map]
            sources = [_source_from_evidence(evidence_map[url]) for url in used_urls]
            artifact = _write_answer_artifact(
                ctx,
                run_id=run_id,
                answer_markdown=str(fallback_payload.get("answer_markdown") or "").strip(),
                depth=depth,
                rounds=round_index,
                sources_used=len(sources),
            )
            assumptions.append("judge_next_query_missing")
            assumptions.append("answer_fallback:insufficient_signal")
            return SkillResult(
                what_i_did=f"Проведён web research: прочитано {len(evidence_map)} страниц, раундов {round_index}",
                sources=sources,
                assumptions=assumptions,
                confidence=0.35 if sources else 0.1,
                artifacts=[artifact],
                events=progress_events,
            )
        current_query = next_query

    if evidence_map:
        fallback_payload = _compose_answer_fallback(query=current_query or query, evidence_map=evidence_map)
        used_urls = [url for url in fallback_payload.get("used_urls", []) if isinstance(url, str) and url in evidence_map]
        sources = [_source_from_evidence(evidence_map[url]) for url in used_urls]
        artifact = _write_answer_artifact(
            ctx,
            run_id=run_id,
            answer_markdown=str(fallback_payload.get("answer_markdown") or "").strip(),
            depth=depth,
            rounds=max_rounds,
            sources_used=len(sources),
        )
        assumptions.append("insufficient_evidence_limits_reached")
        assumptions.append("answer_fallback:max_rounds_reached")
        return SkillResult(
            what_i_did=f"Проведён web research: прочитано {len(evidence_map)} страниц, раундов {max_rounds}",
            sources=sources,
            assumptions=assumptions,
            confidence=0.35 if sources else 0.1,
            artifacts=[artifact],
            events=progress_events,
        )

    return _deep_failed(max_rounds, len(evidence_map), assumptions, "insufficient_evidence_limits_reached", events=progress_events)


def run(inputs: dict, ctx) -> SkillResult:
    query = _normalize_query(inputs.get("query") or ctx.run.get("query_text", ""))
    urls = _normalize_urls(inputs.get("urls"))
    mode = _resolve_mode(inputs.get("mode"), query)

    if mode == MODE_CANDIDATES:
        return _run_candidates_mode(query, urls, ctx)

    depth = _resolve_depth(inputs.get("depth"), query)
    style_hint = _resolve_style_hint(inputs, ctx)
    max_rounds = _coerce_positive_int(inputs.get("max_rounds"), DEFAULT_MAX_ROUNDS)
    max_sources_total = _coerce_positive_int(inputs.get("max_sources_total"), DEFAULT_MAX_SOURCES_TOTAL)
    max_pages_fetch = _coerce_positive_int(inputs.get("max_pages_fetch"), DEFAULT_MAX_PAGES_FETCH)
    return _run_deep_mode(
        query,
        urls,
        depth=depth,
        style_hint=style_hint,
        max_rounds=max_rounds,
        max_sources_total=max_sources_total,
        max_pages_fetch=max_pages_fetch,
        ctx=ctx,
    )
