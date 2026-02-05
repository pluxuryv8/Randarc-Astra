from __future__ import annotations

import re
from typing import Any, Protocol

import requests

from core import secrets


class SearchClient(Protocol):
    def search(self, query: str, urls: list[str] | None = None) -> list[dict[str, Any]]:
        ...


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


def build_search_client(settings: dict) -> SearchClient:
    cfg = settings.get("search") or {}
    provider = cfg.get("provider")
    if provider == "yandex":
        api_key = secrets.get_secret("YANDEX_API_KEY")
        search_url = cfg.get("search_url")
        if not api_key or not search_url:
            raise RuntimeError("Не настроено")
        return YandexSearchClient(api_key, search_url)

    return StubSearchClient(cfg.get("stub_file"))


def _extract_urls(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"https?://[^\s)]+", text)
