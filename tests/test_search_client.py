from __future__ import annotations

import pytest

import core.providers.search_client as search_client


def test_build_search_client_defaults_to_ddgs():
    client = search_client.build_search_client({})
    assert isinstance(client, search_client.DDGSMetaSearchClient)


def test_build_search_client_stub_provider():
    client = search_client.build_search_client({"search": {"provider": "stub"}})
    assert isinstance(client, search_client.StubSearchClient)


def test_build_search_client_unknown_provider():
    with pytest.raises(RuntimeError, match="unknown search provider"):
        search_client.build_search_client({"search": {"provider": "unknown"}})


def test_build_search_client_yandex_requires_config(monkeypatch):
    monkeypatch.setattr(search_client.secrets, "get_secret", lambda _name: None)
    with pytest.raises(RuntimeError, match="YANDEX_API_KEY"):
        search_client.build_search_client({"search": {"provider": "yandex", "search_url": ""}})


def test_ddgs_client_maps_fields(monkeypatch):
    class FakeDDGS:
        def text(self, query: str, max_results: int):
            assert query == "test query"
            assert max_results == 3
            return [
                {"href": "https://example.com/a", "title": "A", "body": "Snippet A"},
                {"url": "https://example.com/b", "title": "B", "snippet": "Snippet B"},
                {"href": "", "title": "skip"},
                "skip",
            ]

    monkeypatch.setattr(search_client, "_load_ddgs_class", lambda: FakeDDGS)

    client = search_client.DDGSMetaSearchClient(max_results=3)
    results = client.search("test query")
    assert results == [
        {"url": "https://example.com/a", "title": "A", "snippet": "Snippet A"},
        {"url": "https://example.com/b", "title": "B", "snippet": "Snippet B"},
    ]


def test_ddgs_client_uses_urls_without_network(monkeypatch):
    called = {"value": False}

    def _load_ddgs():
        called["value"] = True
        raise AssertionError("ddgs must not be called when urls are provided")

    monkeypatch.setattr(search_client, "_load_ddgs_class", _load_ddgs)

    client = search_client.DDGSMetaSearchClient()
    results = client.search(
        "ignored query",
        urls=["https://example.com/1", "https://example.com/2"],
    )

    assert called["value"] is False
    assert results == [
        {"url": "https://example.com/1", "title": None, "snippet": None},
        {"url": "https://example.com/2", "title": None, "snippet": None},
    ]
