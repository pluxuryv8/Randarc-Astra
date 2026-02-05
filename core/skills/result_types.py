from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceCandidate:
    url: str
    title: str | None = None
    domain: str | None = None
    quality: str | None = None
    snippet: str | None = None
    retrieved_at: str | None = None
    pinned: bool = False


@dataclass
class FactCandidate:
    key: str
    value: Any
    confidence: float = 0.0
    source_ids: list[str] = field(default_factory=list)
    created_at: str | None = None


@dataclass
class ArtifactCandidate:
    type: str
    title: str
    content_uri: str
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None


@dataclass
class SkillResult:
    what_i_did: str
    sources: list[SourceCandidate] = field(default_factory=list)
    facts: list[FactCandidate] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    next_actions: list[str] = field(default_factory=list)
    artifacts: list[ArtifactCandidate] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
