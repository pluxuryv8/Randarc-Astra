from __future__ import annotations

from typing import Any

import requests

DEFAULT_USER_AGENT = "randarc-astra-web-fetch/1.0"


def fetch_url(
    url: str,
    *,
    timeout_s: int = 15,
    max_bytes: int = 2_000_000,
    user_agent: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "url": url,
        "status_code": None,
        "final_url": url,
        "content_type": "",
        "html": "",
        "text": "",
        "error": None,
    }

    if not isinstance(url, str) or not url.strip():
        result["error"] = "invalid_url"
        return result

    headers = {
        "User-Agent": user_agent or DEFAULT_USER_AGENT,
        "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
    }
    connect_timeout = min(5, max(1, int(timeout_s)))
    read_timeout = max(1, int(timeout_s))

    try:
        response = requests.get(
            url.strip(),
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=(connect_timeout, read_timeout),
        )
    except requests.RequestException as exc:
        result["error"] = f"request_failed:{exc.__class__.__name__}"
        return result

    result["status_code"] = response.status_code
    result["final_url"] = response.url or url
    content_type = (response.headers.get("Content-Type") or "").strip().lower()
    result["content_type"] = content_type

    if response.status_code >= 400:
        result["error"] = f"http_status_{response.status_code}"
        return result

    if not _is_supported_text_content_type(content_type):
        result["error"] = "unsupported_content_type"
        return result

    body, too_large = _read_with_limit(response, max_bytes=max_bytes)
    if too_large:
        result["error"] = "response_too_large"
        return result

    charset = response.encoding or "utf-8"
    decoded = body.decode(charset, errors="replace")

    if _is_html_content_type(content_type):
        result["html"] = decoded
    else:
        result["text"] = decoded
    return result


def _read_with_limit(response: requests.Response, *, max_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            return b"", True
        chunks.append(chunk)
    return b"".join(chunks), False


def _is_html_content_type(content_type: str) -> bool:
    main_type = content_type.split(";", 1)[0].strip()
    return main_type in {"text/html", "application/xhtml+xml"}


def _is_supported_text_content_type(content_type: str) -> bool:
    main_type = content_type.split(";", 1)[0].strip()
    if not main_type:
        return False
    if main_type.startswith("text/"):
        return True
    return main_type in {"application/xhtml+xml"}
