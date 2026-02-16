from __future__ import annotations

import re
from typing import Any, Protocol

import requests

from core import secrets

DEFAULT_DDGS_MAX_RESULTS = 8


class SearchClient(Protocol):
    def search(self, query: str, urls: list[str] | None = None) -> list[dict[str, Any]]:
        ...


class DDGSMetaSearchClient:
    def __init__(self, max_results: int = DEFAULT_DDGS_MAX_RESULTS):
        self.max_results = max(1, int(max_results))

    def search(self, query: str, urls: list[str] | None = None) -> list[dict[str, Any]]:
        if urls:
            return [{"url": url, "title": None, "snippet": None} for url in urls if url]
        if not query:
            return []

        ddgs_cls = _load_ddgs_class()
        ddgs = ddgs_cls()
        raw_items = ddgs.text(query, max_results=self.max_results)

        results: list[dict[str, Any]] = []
        for item in raw_items or []:
            if not isinstance(item, dict):
                continue
            url = item.get("href") or item.get("url")
            if not url:
                continue
            results.append(
                {
                    "url": url,
                    "title": item.get("title"),
                    "snippet": item.get("body") or item.get("snippet"),
                }
            )
        return results


class YandexSearchClient:
    def __init__(self, api_key: str, search_url: str):
        self.api_key = api_key
        self.search_url = search_url

    def search(self, query: str, urls: list[str] | None = None) -> list[dict[str, Any]]:
        if not query:
            return []
        payload = {"query": query}
        headers = {"Authorization": f"Api-Key {self.api_key}", "Content-Type": "application/json"}
        resp = requests.post(self.search_url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("results", []):
            results.append({
                "url": item.get("url"),
                "title": item.get("title"),
                "snippet": item.get("snippet"),
            })
        return results


class StubSearchClient:
    def __init__(self, stub_file: str | None = None):
        self.stub_file = stub_file

    def search(self, query: str, urls: list[str] | None = None) -> list[dict[str, Any]]:
        resolved = urls or _extract_urls(query)
        if not resolved and self.stub_file:
            try:
                with open(self.stub_file, "r", encoding="utf-8") as handle:
                    resolved = [line.strip() for line in handle if line.strip()]
            except FileNotFoundError:
                resolved = []
        return [{"url": u, "title": None, "snippet": None} for u in resolved]


def build_search_client(settings: dict | None) -> SearchClient:
    cfg: dict[str, Any] = {}
    if isinstance(settings, dict):
        raw_cfg = settings.get("search") or {}
        if not isinstance(raw_cfg, dict):
            raise RuntimeError("search settings must be an object")
        cfg = raw_cfg

    provider_raw = cfg.get("provider")
    provider = "ddgs" if provider_raw in (None, "") else str(provider_raw).strip().lower()

    if provider == "ddgs":
        return DDGSMetaSearchClient(max_results=_coerce_max_results(cfg.get("max_results")))

    if provider == "yandex":
        api_key = secrets.get_secret("YANDEX_API_KEY")
        search_url = cfg.get("search_url")
        if not api_key or not search_url:
            raise RuntimeError("search provider 'yandex' requires YANDEX_API_KEY and search.search_url")
        return YandexSearchClient(api_key, search_url)

    if provider == "stub":
        return StubSearchClient(cfg.get("stub_file"))

    raise RuntimeError(f"unknown search provider: {provider}")


def _extract_urls(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"https?://[^\s)]+", text)


def _coerce_max_results(value: Any) -> int:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        if parsed > 0:
            return parsed
    return DEFAULT_DDGS_MAX_RESULTS


def _load_ddgs_class():
    try:
        from ddgs import DDGS
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("search provider 'ddgs' requires package 'ddgs'") from exc
    return DDGS
