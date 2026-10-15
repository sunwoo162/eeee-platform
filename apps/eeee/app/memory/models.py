from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


MemoryKind = Literal[
    "success_pattern",
    "failure_pattern",
    "qa_rule",
    "regression_rule",
    "agent_routing_hint",
    "playbook",
    "user_preference",
]
PromotionState = Literal["candidate", "active", "superseded", "revoked"]


class MemoryStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    kind: MemoryKind
    content: str = Field(min_length=1)
    scope: dict[str, Any]
    source_project_id: str = Field(min_length=1)
    source_artifact_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    verification_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    promotion_state: PromotionState = "candidate"
    created_at: datetime


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: MemoryKind
    content: str = Field(min_length=1)
    scope: dict[str, Any]
    source_project_id: str = Field(min_length=1)
    source_type: Literal["conversation", "project_outcome"] = "project_outcome"
    source_message_id: str | None = None
    source_request_id: str | None = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    verification_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    status: MemoryStatus
    created_at: datetime
    last_verified_at: datetime | None = None
    expires_at: datetime | None = None
    superseded_by_id: str | None = None
    approved_by: str | None = None
    user_editable: bool = True
