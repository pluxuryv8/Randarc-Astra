from __future__ import annotations

import json
from typing import Any, Protocol

import requests

from core import secrets


class LLMClient(Protocol):
    def chat(self, messages: list[dict[str, Any]], model: str | None = None, temperature: float = 0.2, json_schema: dict | None = None, tools: list[dict] | None = None) -> dict:
        ...


class OpenAIClient:
    def __init__(self, api_key: str, base_url: str, model: str | None = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(self, messages: list[dict[str, Any]], model: str | None = None, temperature: float = 0.2, json_schema: dict | None = None, tools: list[dict] | None = None) -> dict:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_schema:
            payload["response_format"] = {"type": "json_schema", "json_schema": json_schema}
        if tools:
            payload["tools"] = tools

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


class YandexGPTClient:
    def __init__(self, api_key: str, endpoint: str, model: str | None = None, auth_header: str | None = None):
        self.api_key = api_key
        self.endpoint = endpoint
        self.model = model
        self.auth_header = auth_header or "Authorization"

    def chat(self, messages: list[dict[str, Any]], model: str | None = None, temperature: float = 0.2, json_schema: dict | None = None, tools: list[dict] | None = None) -> dict:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_schema:
            payload["json_schema"] = json_schema
        if tools:
            payload["tools"] = tools
        resp = requests.post(
            self.endpoint,
            headers={self.auth_header: f"Api-Key {self.api_key}"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


class GigaChatClient:
    def __init__(self, api_key: str, endpoint: str, model: str | None = None, auth_header: str | None = None):
        self.api_key = api_key
        self.endpoint = endpoint
        self.model = model
        self.auth_header = auth_header or "Authorization"

    def chat(self, messages: list[dict[str, Any]], model: str | None = None, temperature: float = 0.2, json_schema: dict | None = None, tools: list[dict] | None = None) -> dict:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_schema:
            payload["json_schema"] = json_schema
        if tools:
            payload["tools"] = tools
        resp = requests.post(
            self.endpoint,
            headers={self.auth_header: f"Bearer {self.api_key}"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


def build_llm_client(settings: dict) -> LLMClient:
    llm_settings = settings.get("llm") or {}
    provider = llm_settings.get("provider")
    if not provider:
        raise RuntimeError("Не настроено")

    if provider == "openai":
        api_key = secrets.get_secret("OPENAI_API_KEY")
        base_url = llm_settings.get("base_url")
        if not api_key or not base_url:
            raise RuntimeError("Не настроено")
        return OpenAIClient(api_key, base_url, llm_settings.get("model"))

    if provider == "yandex":
        api_key = secrets.get_secret("YANDEX_API_KEY")
        endpoint = llm_settings.get("endpoint")
        if not api_key or not endpoint:
            raise RuntimeError("Не настроено")
        return YandexGPTClient(api_key, endpoint, llm_settings.get("model"), llm_settings.get("auth_header"))

    if provider == "gigachat":
        api_key = secrets.get_secret("GIGACHAT_API_KEY")
        endpoint = llm_settings.get("endpoint")
        if not api_key or not endpoint:
            raise RuntimeError("Не настроено")
        return GigaChatClient(api_key, endpoint, llm_settings.get("model"), llm_settings.get("auth_header"))

    raise RuntimeError("Не настроено")
