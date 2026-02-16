from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import requests


class DesktopBridge:
    def __init__(self) -> None:
        base_url = os.getenv("ASTRA_BRIDGE_BASE_URL")
        if not base_url:
            port = os.getenv("ASTRA_BRIDGE_PORT") or os.getenv("ASTRA_DESKTOP_BRIDGE_PORT", "43124")
            base_url = f"http://127.0.0.1:{port}"
        self.base_url = base_url.rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"Некорректный ASTRA_BRIDGE_BASE_URL: {self.base_url}")

    def computer_preview(self, actions: list[dict]) -> dict[str, Any]:
        return self._post("/computer/preview", {"actions": actions})

    def computer_execute(self, actions: list[dict]) -> dict[str, Any]:
        return self._post("/computer/execute", {"actions": actions})

    def shell_preview(self, command: str) -> dict[str, Any]:
        return self._post("/shell/preview", {"command": command})

    def shell_execute(self, command: str) -> dict[str, Any]:
        return self._post("/shell/execute", {"command": command})

    def autopilot_capture(self, max_width: int = 1280, quality: int = 60) -> dict[str, Any]:
        return self._post("/autopilot/capture", {"max_width": max_width, "quality": quality})

    def autopilot_act(self, action: dict[str, Any], image_width: int, image_height: int) -> dict[str, Any]:
        return self._post("/autopilot/act", {"action": action, "image_width": image_width, "image_height": image_height})

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(f"{self.base_url}{path}", json=payload, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(resp.text or "Ошибка обращения к мосту")
        return resp.json() if resp.text else {}
