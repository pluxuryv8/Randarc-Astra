from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str
    tags: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    tags: Optional[list[str]] = None
    settings: Optional[dict[str, Any]] = None


class RunCreate(BaseModel):
    query_text: str
    mode: str = "research"
    parent_run_id: Optional[str] = None
    purpose: Optional[str] = None


class BootstrapRequest(BaseModel):
    token: str


class ApprovalDecision(BaseModel):
    limit: Optional[int] = None
    action: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    decision: Optional[ApprovalDecision] = None


class MemoryCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    title: Optional[str] = None
    content: str
    tags: list[str] = Field(default_factory=list)
    source: Optional[str] = None
    from_: Optional[str] = Field(default="user_command", alias="from")
    run_id: Optional[str] = None


class ReminderCreateRequest(BaseModel):
    due_at: str
    text: str
    delivery: Optional[str] = None
    run_id: Optional[str] = None
    source: Optional[str] = None
