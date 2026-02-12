from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


_REMINDER_TRIGGERS = ("напомни", "напомнить", "напоминание")


def _get_timezone() -> ZoneInfo:
    raw = os.getenv("ASTRA_TIMEZONE", "Russia").strip() or "Russia"
    if raw.lower() in ("russia", "msk", "moscow"):
        return ZoneInfo("Europe/Moscow")
    try:
        return ZoneInfo(raw)
    except Exception:
        return ZoneInfo("UTC")


def _now_in_tz(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def _strip_reminder_phrase(text: str) -> str:
    cleaned = re.sub(r"\b(" + "|".join(map(re.escape, _REMINDER_TRIGGERS)) + r")\b", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _clean_reminder_text(text: str) -> str:
    cleaned = re.sub(r"^[\s:–—-]+", "", text).strip()
    cleaned = re.sub(r"^(а|про|о)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def parse_reminder_text(text: str, now: datetime | None = None) -> tuple[str | None, str | None, str | None]:
    tz = _get_timezone()
    now_dt = now or _now_in_tz(tz)
    normalized = re.sub(r"\s+", " ", text.strip().lower())

    if not normalized:
        return None, None, "Когда напомнить?"

    match_in = re.search(r"через\s+(\d+)\s*(минут|минуты|минута|час|часа|часов)", normalized)
    if match_in:
        value = int(match_in.group(1))
        unit = match_in.group(2)
        delta = timedelta(minutes=value) if unit.startswith("мин") else timedelta(hours=value)
        due_dt = now_dt + delta
        reminder_text = _strip_reminder_phrase(text)
        reminder_text = re.sub(match_in.group(0), "", reminder_text, flags=re.IGNORECASE).strip()
        reminder_text = _clean_reminder_text(reminder_text)
        if not reminder_text:
            return None, None, "Что именно нужно напомнить?"
        return _to_utc_iso(due_dt), reminder_text, None

    match_relative = re.search(r"(завтра|сегодня)\s+в\s+(\d{1,2}):(\d{2})", normalized)
    if match_relative:
        day = match_relative.group(1)
        hour = int(match_relative.group(2))
        minute = int(match_relative.group(3))
        base_date = now_dt.date()
        if day == "завтра":
            base_date = base_date + timedelta(days=1)
        due_dt = datetime(
            year=base_date.year,
            month=base_date.month,
            day=base_date.day,
            hour=hour,
            minute=minute,
            tzinfo=tz,
        )
        if due_dt < now_dt:
            due_dt = due_dt + timedelta(days=1)
        reminder_text = _strip_reminder_phrase(text)
        reminder_text = re.sub(match_relative.group(0), "", reminder_text, flags=re.IGNORECASE).strip()
        reminder_text = _clean_reminder_text(reminder_text)
        if not reminder_text:
            return None, None, "Что именно нужно напомнить?"
        return _to_utc_iso(due_dt), reminder_text, None

    match_time = re.search(r"\bв\s+(\d{1,2}):(\d{2})", normalized)
    if match_time:
        hour = int(match_time.group(1))
        minute = int(match_time.group(2))
        base_date = now_dt.date()
        due_dt = datetime(
            year=base_date.year,
            month=base_date.month,
            day=base_date.day,
            hour=hour,
            minute=minute,
            tzinfo=tz,
        )
        if due_dt < now_dt:
            due_dt = due_dt + timedelta(days=1)
        reminder_text = _strip_reminder_phrase(text)
        reminder_text = re.sub(match_time.group(0), "", reminder_text, flags=re.IGNORECASE).strip()
        reminder_text = _clean_reminder_text(reminder_text)
        if not reminder_text:
            return None, None, "Что именно нужно напомнить?"
        return _to_utc_iso(due_dt), reminder_text, None

    if any(trigger in normalized for trigger in _REMINDER_TRIGGERS):
        return None, None, "Когда напомнить?"

    return None, None, "Когда напомнить?"


def _to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.isoformat().replace("+00:00", "Z")
