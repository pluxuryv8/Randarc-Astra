from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from io import BytesIO


@dataclass
class OCRResult:
    text: str
    lines: list[str] | None = None
    confidence: float | None = None
    language: str | None = None
    ts: float = field(default_factory=time.time)


class OCRProvider:
    name = "unknown"

    def extract(self, image_bytes: bytes, lang: str | None = None) -> OCRResult:
        raise NotImplementedError


class TesseractOCRProvider(OCRProvider):
    name = "tesseract"

    def __init__(self, default_lang: str = "eng+rus") -> None:
        if not shutil.which("tesseract"):
            raise RuntimeError("tesseract_not_found")
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
        except Exception as exc:  # pragma: no cover - import error
            raise RuntimeError("pytesseract_not_available") from exc

        self._pytesseract = pytesseract
        self._Image = Image
        self.default_lang = default_lang

    def extract(self, image_bytes: bytes, lang: str | None = None) -> OCRResult:
        if not image_bytes:
            return OCRResult(text="", lines=[], confidence=None, language=lang or self.default_lang)

        image = self._Image.open(BytesIO(image_bytes))
        lang_value = lang or self.default_lang

        text = self._pytesseract.image_to_string(image, lang=lang_value) or ""
        data = self._pytesseract.image_to_data(image, lang=lang_value, output_type=self._pytesseract.Output.DICT)

        confidences: list[float] = []
        for value in data.get("conf", []):
            try:
                val = float(value)
            except (TypeError, ValueError):
                continue
            if val >= 0:
                confidences.append(val)

        confidence = None
        if confidences:
            confidence = sum(confidences) / len(confidences)

        lines = [line for line in (text.splitlines() if text else []) if line.strip()]

        return OCRResult(text=text, lines=lines, confidence=confidence, language=lang_value)


@dataclass
class OCRCache:
    entries: dict[str, OCRResult] = field(default_factory=dict)

    def get(self, key: str) -> OCRResult | None:
        return self.entries.get(key)

    def set(self, key: str, value: OCRResult) -> None:
        self.entries[key] = value


def get_default_provider() -> OCRProvider | None:
    try:
        return TesseractOCRProvider()
    except Exception:
        return None
