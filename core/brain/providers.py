from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from core.llm_routing import _redact_secrets

_ROOT_DIR = Path(__file__).resolve().parents[2]
_ARTIFACT_DIR = _ROOT_DIR / "artifacts" / "local_llm_failures"
_MAX_PAYLOAD_CHARS = 5000


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _sanitize_value(value: Any, max_chars: int) -> Any:
    if isinstance(value, str):
        redacted, _ = _redact_secrets(value)
        return _truncate(redacted, max_chars)
    if isinstance(value, dict):
        return {key: _sanitize_value(item, max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item, max_chars) for item in value]
    return value


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if not isinstance(content, str):
            try:
                content = json.dumps(content, ensure_ascii=False)
            except Exception:
                content = str(content)
        normalized.append({"role": role, "content": content})
    return normalized


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        role = str(message.get("role", "user")).strip().lower()
        content = message.get("content", "")
        if not isinstance(content, str):
            try:
                content = json.dumps(content, ensure_ascii=False)
            except Exception:
                content = str(content)
        content = content.strip()
        if not content:
            continue
        if role == "system":
            label = "System"
        elif role == "assistant":
            label = "Assistant"
        else:
            label = "User"
        parts.append(f"{label}:\n{content}")
    parts.append("Assistant:")
    return "\n\n".join(parts)


def _normalize_json_schema(schema: dict | None) -> dict | None:
    if not schema:
        return None
    if isinstance(schema, dict) and "schema" in schema and isinstance(schema.get("schema"), dict):
        return schema.get("schema")
    if isinstance(schema, dict) and "type" in schema:
        return schema
    return None


def _write_failure_artifact(
    *,
    payload: dict[str, Any],
    response_status: int | None,
    response_text: str | None,
    run_id: str | None,
    step_id: str | None,
    model: str,
    purpose: str | None,
    variant: str,
) -> str:
    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_run = run_id or "unknown"
    safe_step = step_id or "unknown"
    filename = f"{ts}_{safe_run}_{safe_step}_{variant}.json"
    path = _ARTIFACT_DIR / filename

    artifact = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "step_id": step_id,
        "purpose": purpose,
        "model": model,
        "variant": variant,
        "request_payload": _sanitize_value(payload, _MAX_PAYLOAD_CHARS),
        "response_status": response_status,
        "response_text": _truncate(_sanitize_value(response_text or "", _MAX_PAYLOAD_CHARS), _MAX_PAYLOAD_CHARS),
    }
    try:
        path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # Best-effort logging; avoid breaking provider flow.
        return str(path)
    try:
        return str(path.relative_to(_ROOT_DIR))
    except ValueError:
        return str(path)


def _extract_error_text(resp: requests.Response) -> str | None:
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            return str(data.get("error"))
    except Exception:
        return resp.text
    return resp.text


def _missing_model_hint(error_text: str | None) -> str | None:
    if not error_text:
        return None
    lowered = error_text.lower()
    if "model" in lowered and "not found" in lowered:
        return "Model not found. Install via ./scripts/models.sh install."
    return None


@dataclass
class ProviderResult:
    text: str
    usage: dict | None
    raw: dict
    model_id: str | None = None


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        error_type: str | None = None,
        artifact_path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.error_type = error_type or "provider_error"
        self.artifact_path = artifact_path


class LocalLLMProvider:
    def __init__(self, base_url: str, chat_model: str, code_model: str, timeout_s: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.code_model = code_model
        self.timeout_s = timeout_s

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        model_kind: str = "chat",
        temperature: float = 0.2,
        top_p: float | None = None,
        repeat_penalty: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict | None = None,
        tools: list[dict] | None = None,
        run_id: str | None = None,
        step_id: str | None = None,
        purpose: str | None = None,
    ) -> ProviderResult:
        model = model or (self.code_model if model_kind == "code" else self.chat_model)
        normalized_messages = _normalize_messages(messages)
        schema = _normalize_json_schema(json_schema)
        allow_generate_fallback = schema is None and not tools
        payload: dict[str, Any] = {
            "model": model,
            "messages": normalized_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        if top_p is not None:
            payload["options"]["top_p"] = top_p
        if repeat_penalty is not None:
            payload["options"]["repeat_penalty"] = repeat_penalty
        if max_tokens is not None:
            payload["options"]["num_predict"] = int(max_tokens)

        if schema:
            payload["format"] = schema
        if tools:
            payload["tools"] = tools

        try:
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            if allow_generate_fallback:
                return self._generate(
                    model=model,
                    normalized_messages=normalized_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    run_id=run_id,
                    step_id=step_id,
                    purpose=purpose,
                )
            raise ProviderError(f"Local LLM request failed: {exc}", provider="local", error_type="connection_error") from exc

        if resp.status_code >= 500:
            artifact_path = _write_failure_artifact(
                payload=payload,
                response_status=resp.status_code,
                response_text=resp.text,
                run_id=run_id,
                step_id=step_id,
                model=model,
                purpose=purpose,
                variant="primary",
            )
            simplified_payload: dict[str, Any] = {
                "model": model,
                "messages": normalized_messages,
                "stream": False,
            }
            try:
                retry_resp = requests.post(
                    f"{self.base_url}/api/chat",
                    json=simplified_payload,
                    timeout=self.timeout_s,
                )
            except requests.RequestException as exc:
                if allow_generate_fallback:
                    return self._generate(
                        model=model,
                        normalized_messages=normalized_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        run_id=run_id,
                        step_id=step_id,
                        purpose=purpose,
                    )
                raise ProviderError(
                    f"Local LLM request failed: {exc}",
                    provider="local",
                    error_type="connection_error",
                    artifact_path=artifact_path,
                ) from exc
            if retry_resp.status_code >= 400:
                if retry_resp.status_code >= 500 and allow_generate_fallback:
                    return self._generate(
                        model=model,
                        normalized_messages=normalized_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        run_id=run_id,
                        step_id=step_id,
                        purpose=purpose,
                    )
                error_text = _extract_error_text(retry_resp)
                hint = _missing_model_hint(error_text)
                retry_artifact = _write_failure_artifact(
                    payload=simplified_payload,
                    response_status=retry_resp.status_code,
                    response_text=retry_resp.text,
                    run_id=run_id,
                    step_id=step_id,
                    model=model,
                    purpose=purpose,
                    variant="simplified",
                )
                message = f"Local LLM HTTP {retry_resp.status_code}"
                if error_text:
                    message = f"{message}: {error_text}"
                if hint:
                    message = f"{message} {hint}"
                raise ProviderError(
                    message,
                    provider="local",
                    status_code=retry_resp.status_code,
                    error_type="model_not_found" if hint else "http_error",
                    artifact_path=retry_artifact or artifact_path,
                )
            try:
                data = retry_resp.json()
            except json.JSONDecodeError as exc:
                if allow_generate_fallback:
                    return self._generate(
                        model=model,
                        normalized_messages=normalized_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        run_id=run_id,
                        step_id=step_id,
                        purpose=purpose,
                    )
                raise ProviderError(
                    "Local LLM returned invalid JSON",
                    provider="local",
                    status_code=retry_resp.status_code,
                    error_type="invalid_json",
                    artifact_path=artifact_path,
                ) from exc

            message = data.get("message") or {}
            text = message.get("content") or ""
            usage = {
                "prompt_eval_count": data.get("prompt_eval_count"),
                "eval_count": data.get("eval_count"),
                "total_duration": data.get("total_duration"),
            }
            return ProviderResult(text=text, usage=usage, raw=data, model_id=model)

        if resp.status_code >= 400:
            error_text = _extract_error_text(resp)
            hint = _missing_model_hint(error_text)
            artifact_path = _write_failure_artifact(
                payload=payload,
                response_status=resp.status_code,
                response_text=resp.text,
                run_id=run_id,
                step_id=step_id,
                model=model,
                purpose=purpose,
                variant="primary",
            )
            message = f"Local LLM HTTP {resp.status_code}"
            if error_text:
                message = f"{message}: {error_text}"
            if hint:
                message = f"{message} {hint}"
            raise ProviderError(
                message,
                provider="local",
                status_code=resp.status_code,
                error_type="model_not_found" if hint else "http_error",
                artifact_path=artifact_path,
            )

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            if allow_generate_fallback:
                return self._generate(
                    model=model,
                    normalized_messages=normalized_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    run_id=run_id,
                    step_id=step_id,
                    purpose=purpose,
                )
            raise ProviderError("Local LLM returned invalid JSON", provider="local", status_code=resp.status_code, error_type="invalid_json") from exc

        message = data.get("message") or {}
        text = message.get("content") or ""
        usage = {
            "prompt_eval_count": data.get("prompt_eval_count"),
            "eval_count": data.get("eval_count"),
            "total_duration": data.get("total_duration"),
        }
        return ProviderResult(text=text, usage=usage, raw=data, model_id=model)

    def _generate(
        self,
        *,
        model: str,
        normalized_messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
        run_id: str | None,
        step_id: str | None,
        purpose: str | None,
    ) -> ProviderResult:
        prompt = _messages_to_prompt(normalized_messages)
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = int(max_tokens)
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Local LLM request failed: {exc}", provider="local", error_type="connection_error") from exc

        if resp.status_code >= 400:
            error_text = _extract_error_text(resp)
            hint = _missing_model_hint(error_text)
            artifact_path = _write_failure_artifact(
                payload=payload,
                response_status=resp.status_code,
                response_text=resp.text,
                run_id=run_id,
                step_id=step_id,
                model=model,
                purpose=purpose,
                variant="generate_fallback",
            )
            message = f"Local LLM HTTP {resp.status_code}"
            if error_text:
                message = f"{message}: {error_text}"
            if hint:
                message = f"{message} {hint}"
            raise ProviderError(
                message,
                provider="local",
                status_code=resp.status_code,
                error_type="model_not_found" if hint else "http_error",
                artifact_path=artifact_path,
            )
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("Local LLM returned invalid JSON", provider="local", status_code=resp.status_code, error_type="invalid_json") from exc
        text = data.get("response") or ""
        usage = {
            "prompt_eval_count": data.get("prompt_eval_count"),
            "eval_count": data.get("eval_count"),
            "total_duration": data.get("total_duration"),
        }
        return ProviderResult(text=text, usage=usage, raw=data, model_id=model)


class CloudLLMProvider:
    def __init__(self, base_url: str, api_key: str, timeout_s: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        json_schema: dict | None = None,
        tools: list[dict] | None = None,
    ) -> ProviderResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if json_schema:
            payload["response_format"] = {"type": "json_schema", "json_schema": json_schema}
        if tools:
            payload["tools"] = tools

        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Cloud LLM request failed: {exc}", provider="cloud", error_type="connection_error") from exc

        if resp.status_code >= 400:
            raise ProviderError(
                f"Cloud LLM HTTP {resp.status_code}",
                provider="cloud",
                status_code=resp.status_code,
                error_type="http_error",
            )

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("Cloud LLM returned invalid JSON", provider="cloud", status_code=resp.status_code, error_type="invalid_json") from exc

        text = ""
        if "choices" in data:
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage")
        return ProviderResult(text=text, usage=usage, raw=data, model_id=model)
