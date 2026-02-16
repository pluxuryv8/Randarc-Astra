from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

DEFAULT_MAX_CHARS = 25_000

_SKIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "svg"}
_BREAK_TAGS = {
    "article",
    "aside",
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "main",
    "p",
    "section",
    "tr",
}


class _MainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        tag_name = (tag or "").lower()
        if tag_name in _SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth > 0:
            return
        if tag_name in _BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_name = (tag or "").lower()
        if tag_name in _SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth > 0:
            return
        if tag_name in _BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0:
            return
        if data:
            self.parts.append(data)


def extract_main_text(html: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    if not isinstance(html, str) or not html.strip():
        return ""

    parser = _MainTextParser()
    parser.feed(html)
    parser.close()

    text = unescape("".join(parser.parts))
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = text.strip()

    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "..."
    return text
