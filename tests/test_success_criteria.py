from __future__ import annotations

from core.executor.success_criteria import evaluate_success_checks, parse_success_criteria
from core.ocr.engine import OCRCache, OCRResult


def test_parse_success_criteria_contains():
    checks = parse_success_criteria("contains: Settings")
    assert checks
    assert checks[0]["type"] == "contains_text"


def test_parse_success_criteria_regex_and_not():
    checks = parse_success_criteria("regex: foo\\d+; not_contains: bar")
    assert len(checks) == 2
    assert checks[0]["type"] == "regex_match"
    assert checks[1]["type"] == "not_contains_text"


def test_evaluate_success_checks():
    checks = [
        {"type": "contains_text", "value": "Настройки", "case_sensitive": False},
        {"type": "not_contains_text", "value": "Ошибка"},
    ]
    assert evaluate_success_checks(checks, "Открыты настройки профиля")
    assert not evaluate_success_checks(checks, "Ошибка: Настройки")


def test_ocr_cache_hit():
    cache = OCRCache()
    result = OCRResult(text="hello")
    cache.set("hash1", result)
    assert cache.get("hash1") is result
