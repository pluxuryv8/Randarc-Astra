from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from skills.web_research import skill as web_research


class FakeSearchClient:
    def __init__(self, responses: dict[str, list[dict]]):
        self.responses = responses
        self.calls: list[str] = []

    def search(self, query: str, urls=None):  # noqa: ANN001
        self.calls.append(query)
        return list(self.responses.get(query, []))


def _ctx(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        run={"id": "run-web-1", "query_text": "initial query", "meta": {}},
        plan_step={"id": "step-1"},
        task={"id": "task-1"},
        settings={"search": {"provider": "ddgs"}},
        base_dir=str(tmp_path),
    )


def test_deep_mode_single_round_enough(monkeypatch, tmp_path: Path):
    ctx = _ctx(tmp_path)
    client = FakeSearchClient(
        {
            "initial query": [
                {"url": "https://example.org/a", "title": "A", "snippet": "snippet A"},
                {"url": "https://example.net/b", "title": "B", "snippet": "snippet B"},
            ]
        }
    )
    monkeypatch.setattr(web_research, "build_search_client", lambda _settings: client)
    monkeypatch.setattr(
        web_research,
        "_fetch_and_extract_cached",
        lambda _ctx, *, run_id, candidate, timeout_s=15, max_bytes=2_000_000: {
            "url": candidate["url"],
            "title": candidate.get("title"),
            "domain": candidate.get("domain"),
            "snippet": candidate.get("snippet"),
            "final_url": candidate["url"],
            "extracted_text": f"text for {candidate['url']}",
            "error": None,
        },
    )
    monkeypatch.setattr(
        web_research,
        "_judge_research",
        lambda *_args, **_kwargs: {
            "decision": "ENOUGH",
            "score": 0.9,
            "why": "enough",
            "next_query": None,
            "missing_topics": [],
            "need_sources": 0,
            "used_urls": ["https://example.org/a", "https://example.net/b"],
        },
    )
    monkeypatch.setattr(
        web_research,
        "_compose_answer",
        lambda *_args, **_kwargs: {
            "answer_markdown": "Краткий ответ [1][2]\n\n## Источники\n[1] https://example.org/a\n[2] https://example.net/b",
            "used_urls": ["https://example.org/a", "https://example.net/b"],
            "unknowns": [],
        },
    )

    result = web_research.run({"query": "initial query", "mode": "deep"}, ctx)

    assert result.confidence > 0.0
    assert len(result.sources) >= 2
    assert result.artifacts
    assert Path(result.artifacts[0].content_uri).exists()


def test_deep_mode_two_rounds_until_enough(monkeypatch, tmp_path: Path):
    ctx = _ctx(tmp_path)
    client = FakeSearchClient(
        {
            "initial query": [{"url": "https://example.org/a", "title": "A", "snippet": "snippet A"}],
            "refined query": [{"url": "https://example.net/b", "title": "B", "snippet": "snippet B"}],
        }
    )
    monkeypatch.setattr(web_research, "build_search_client", lambda _settings: client)
    monkeypatch.setattr(
        web_research,
        "_fetch_and_extract_cached",
        lambda _ctx, *, run_id, candidate, timeout_s=15, max_bytes=2_000_000: {
            "url": candidate["url"],
            "title": candidate.get("title"),
            "domain": candidate.get("domain"),
            "snippet": candidate.get("snippet"),
            "final_url": candidate["url"],
            "extracted_text": f"text for {candidate['url']}",
            "error": None,
        },
    )

    judge_calls = {"count": 0}

    def _judge(*_args, **_kwargs):
        judge_calls["count"] += 1
        if judge_calls["count"] == 1:
            return {
                "decision": "NOT_ENOUGH",
                "score": 0.3,
                "why": "need more",
                "next_query": "refined query",
                "missing_topics": ["details"],
                "need_sources": 1,
                "used_urls": ["https://example.org/a"],
            }
        return {
            "decision": "ENOUGH",
            "score": 0.8,
            "why": "enough",
            "next_query": None,
            "missing_topics": [],
            "need_sources": 0,
            "used_urls": ["https://example.org/a", "https://example.net/b"],
        }

    monkeypatch.setattr(web_research, "_judge_research", _judge)
    monkeypatch.setattr(
        web_research,
        "_compose_answer",
        lambda *_args, **_kwargs: {
            "answer_markdown": "Итог [1][2]\n\n## Источники\n[1] https://example.org/a\n[2] https://example.net/b",
            "used_urls": ["https://example.org/a", "https://example.net/b"],
            "unknowns": [],
        },
    )

    result = web_research.run({"query": "initial query", "mode": "deep", "max_rounds": 3}, ctx)

    assert result.confidence > 0.0
    assert len(result.sources) >= 2
    assert client.calls == ["initial query", "refined query"]


def test_deep_mode_invalid_llm_json(monkeypatch, tmp_path: Path):
    ctx = _ctx(tmp_path)
    client = FakeSearchClient(
        {
            "initial query": [{"url": "https://example.org/a", "title": "A", "snippet": "snippet A"}],
        }
    )
    monkeypatch.setattr(web_research, "build_search_client", lambda _settings: client)
    monkeypatch.setattr(
        web_research,
        "_fetch_and_extract_cached",
        lambda _ctx, *, run_id, candidate, timeout_s=15, max_bytes=2_000_000: {
            "url": candidate["url"],
            "title": candidate.get("title"),
            "domain": candidate.get("domain"),
            "snippet": candidate.get("snippet"),
            "final_url": candidate["url"],
            "extracted_text": f"text for {candidate['url']}",
            "error": None,
        },
    )
    monkeypatch.setattr(web_research, "_judge_research", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("invalid_llm_json")))

    result = web_research.run({"query": "initial query", "mode": "deep"}, ctx)

    assert result.confidence > 0.0
    assert any("judge_fallback:invalid_llm_json" in item for item in result.assumptions)
    assert result.artifacts
    assert any(evt.get("reason_code") == "judge_fallback" for evt in result.events)


def test_deep_mode_fetch_error_keeps_other_sources(monkeypatch, tmp_path: Path):
    ctx = _ctx(tmp_path)
    client = FakeSearchClient(
        {
            "initial query": [
                {"url": "https://example.org/a", "title": "A", "snippet": "snippet A"},
                {"url": "https://example.net/b", "title": "B", "snippet": "snippet B"},
            ]
        }
    )
    monkeypatch.setattr(web_research, "build_search_client", lambda _settings: client)

    def _fetch(_ctx, *, run_id, candidate, timeout_s=15, max_bytes=2_000_000):  # noqa: ARG001
        if candidate["url"] == "https://example.org/a":
            return {
                "url": candidate["url"],
                "title": candidate.get("title"),
                "domain": candidate.get("domain"),
                "snippet": candidate.get("snippet"),
                "final_url": candidate["url"],
                "extracted_text": "",
                "error": "request_failed:Timeout",
            }
        return {
            "url": candidate["url"],
            "title": candidate.get("title"),
            "domain": candidate.get("domain"),
            "snippet": candidate.get("snippet"),
            "final_url": candidate["url"],
            "extracted_text": "valid text",
            "error": None,
        }

    monkeypatch.setattr(web_research, "_fetch_and_extract_cached", _fetch)
    monkeypatch.setattr(
        web_research,
        "_judge_research",
        lambda *_args, **_kwargs: {
            "decision": "ENOUGH",
            "score": 0.6,
            "why": "enough",
            "next_query": None,
            "missing_topics": [],
            "need_sources": 0,
            "used_urls": ["https://example.net/b"],
        },
    )
    monkeypatch.setattr(
        web_research,
        "_compose_answer",
        lambda *_args, **_kwargs: {
            "answer_markdown": "Ответ [1]\n\n## Источники\n[1] https://example.net/b",
            "used_urls": ["https://example.net/b"],
            "unknowns": [],
        },
    )

    result = web_research.run({"query": "initial query", "mode": "deep"}, ctx)

    assert result.confidence > 0.0
    assert len(result.sources) == 1
    assert result.sources[0].url == "https://example.net/b"
    assert any("request_failed:Timeout" in item for item in result.assumptions)


def test_deep_mode_not_enough_without_next_query_returns_fallback_answer(monkeypatch, tmp_path: Path):
    ctx = _ctx(tmp_path)
    client = FakeSearchClient(
        {
            "initial query": [{"url": "https://example.org/a", "title": "A", "snippet": "snippet A"}],
        }
    )
    monkeypatch.setattr(web_research, "build_search_client", lambda _settings: client)
    monkeypatch.setattr(
        web_research,
        "_fetch_and_extract_cached",
        lambda _ctx, *, run_id, candidate, timeout_s=15, max_bytes=2_000_000: {
            "url": candidate["url"],
            "title": candidate.get("title"),
            "domain": candidate.get("domain"),
            "snippet": candidate.get("snippet"),
            "final_url": candidate["url"],
            "extracted_text": "definition and formula text",
            "error": None,
        },
    )
    monkeypatch.setattr(
        web_research,
        "_judge_research",
        lambda *_args, **_kwargs: {
            "decision": "NOT_ENOUGH",
            "score": 0.2,
            "why": "need more",
            "next_query": None,
            "missing_topics": ["details"],
            "need_sources": 1,
            "used_urls": ["https://example.org/a"],
        },
    )

    result = web_research.run({"query": "initial query", "mode": "deep"}, ctx)

    assert result.sources
    assert result.artifacts
    assert any("judge_next_query_missing" in item for item in result.assumptions)


def test_deep_mode_invalid_judge_decision_uses_fallback(monkeypatch, tmp_path: Path):
    ctx = _ctx(tmp_path)
    client = FakeSearchClient(
        {
            "initial query": [{"url": "https://example.org/a", "title": "A", "snippet": "snippet A"}],
        }
    )
    monkeypatch.setattr(web_research, "build_search_client", lambda _settings: client)
    monkeypatch.setattr(
        web_research,
        "_fetch_and_extract_cached",
        lambda _ctx, *, run_id, candidate, timeout_s=15, max_bytes=2_000_000: {
            "url": candidate["url"],
            "title": candidate.get("title"),
            "domain": candidate.get("domain"),
            "snippet": candidate.get("snippet"),
            "final_url": candidate["url"],
            "extracted_text": "definition and formula text",
            "error": None,
        },
    )
    monkeypatch.setattr(
        web_research,
        "_judge_research",
        lambda *_args, **_kwargs: {
            "decision": "",
            "score": 0.0,
            "why": "invalid payload",
            "next_query": None,
            "missing_topics": [],
            "need_sources": 0,
            "used_urls": [],
        },
    )

    result = web_research.run({"query": "initial query", "mode": "deep", "max_rounds": 2}, ctx)

    assert result.sources
    assert result.artifacts
    assert any("judge_fallback:invalid_decision:empty" in item for item in result.assumptions)
    assert any(evt.get("reason_code") == "judge_fallback" for evt in result.events)
