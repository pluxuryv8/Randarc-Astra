from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from core.event_bus import emit
from memory import store


@dataclass
class DeliveryResult:
    ok: bool
    delivery: str
    error: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_telegram_config() -> tuple[str | None, str | None]:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or ""
    return token.strip() or None, chat_id.strip() or None


def _send_telegram_message(token: str, chat_id: str, text: str) -> DeliveryResult:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            if resp.status >= 200 and resp.status < 300 and data.get("ok") is True:
                return DeliveryResult(ok=True, delivery="telegram")
            return DeliveryResult(ok=False, delivery="telegram", error=f"telegram_http_{resp.status}")
    except Exception as exc:
        return DeliveryResult(ok=False, delivery="telegram", error=str(exc))


def _local_delivery(text: str) -> DeliveryResult:
    print(f"[reminder] {text}")
    return DeliveryResult(ok=True, delivery="local")


def _event_run_id(reminder: dict) -> str:
    run_id = reminder.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        return run_id.strip()
    reminder_id = str(reminder.get("id") or "unknown")
    return f"reminder:{reminder_id}"


def _delivery_timezone() -> timezone | ZoneInfo:
    raw = (os.getenv("ASTRA_TIMEZONE") or "").strip()
    if raw:
        try:
            return ZoneInfo(raw)
        except Exception:
            return timezone.utc
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is None:
        return timezone.utc
    return local_tz


def _format_due_for_message(due_at: str | None) -> str:
    if not due_at:
        return "не указано"
    raw = due_at.strip()
    if not raw:
        return "не указано"
    normalized = raw.replace("Z", "+00:00")
    try:
        due_dt = datetime.fromisoformat(normalized)
    except Exception:
        return raw
    if due_dt.tzinfo is None:
        due_dt = due_dt.replace(tzinfo=timezone.utc)
    tz = _delivery_timezone()
    local_dt = due_dt.astimezone(tz)
    today = datetime.now(tz).date()
    day_note = " (сегодня)" if local_dt.date() == today else f" ({local_dt.strftime('%d.%m')})"
    return f"{local_dt.strftime('%H:%M')}{day_note}"


def _format_reminder_message(reminder: dict) -> str:
    text = str(reminder.get("text") or "").strip() or "без текста"
    due_text = _format_due_for_message(reminder.get("due_at"))
    return f"Напоминание: {text}. Время: {due_text}."


class ReminderScheduler:
    def __init__(self, poll_interval: int = 5, batch_size: int = 20) -> None:
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="reminder-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> None:
        if not self._enabled():
            return
        now_iso = _now_iso()
        reminders = store.claim_due_reminders(now_iso, limit=self.batch_size)
        for reminder in reminders:
            self._deliver(reminder)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                # Keep loop alive
                pass
            self._stop.wait(self.poll_interval)

    def _enabled(self) -> bool:
        raw = os.getenv("ASTRA_REMINDERS_ENABLED", "true")
        return raw.lower() not in ("0", "false", "no", "off")

    def _deliver(self, reminder: dict) -> None:
        run_id = reminder.get("run_id")
        event_run_id = _event_run_id(reminder)
        reminder_id = reminder.get("id")
        message_text = _format_reminder_message(reminder)
        emit(event_run_id, "reminder_due", "Напоминание подошло", {"id": reminder_id, "run_id": run_id})

        delivery_pref = reminder.get("delivery") or "local"
        if delivery_pref == "telegram":
            token, chat_id = _get_telegram_config()
            if not token or not chat_id:
                store.mark_reminder_failed(reminder_id, "telegram_not_configured", "local")
                emit(
                    event_run_id,
                    "reminder_failed",
                    "Telegram не настроен",
                    {"id": reminder_id, "error": "telegram_not_configured", "run_id": run_id},
                )
                _local_delivery(message_text)
                return

            attempt_error: str | None = None
            for attempt in range(3):
                result = _send_telegram_message(token, chat_id, message_text)
                if result.ok:
                    store.mark_reminder_sent(reminder_id, result.delivery)
                    emit(
                        event_run_id,
                        "reminder_sent",
                        "Напоминание отправлено",
                        {"id": reminder_id, "delivery": result.delivery, "run_id": run_id},
                    )
                    return
                attempt_error = result.error or "telegram_send_failed"
                time.sleep(1.0 * (2**attempt))

            store.mark_reminder_failed(reminder_id, attempt_error or "telegram_send_failed", "telegram")
            emit(
                event_run_id,
                "reminder_failed",
                "Не удалось отправить в Telegram",
                {"id": reminder_id, "error": attempt_error, "run_id": run_id},
            )
            return

        # Local delivery
        result = _local_delivery(message_text)
        store.mark_reminder_sent(reminder_id, result.delivery)
        emit(
            event_run_id,
            "reminder_sent",
            "Напоминание доставлено локально",
            {"id": reminder_id, "delivery": result.delivery, "run_id": run_id},
        )


_scheduler: Optional[ReminderScheduler] = None


def start_reminder_scheduler() -> ReminderScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = ReminderScheduler()
        _scheduler.start()
    return _scheduler
