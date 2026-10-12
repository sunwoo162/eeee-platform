from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts.execution import SideEffectLevel


ApprovalLevel = Literal["none", "user", "always"]
SelectionStatus = Literal["selected", "needs_clarification", "plugin_required"]


class CapabilityDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    intents: list[str] = Field(min_length=1)
    trigger_phrases: list[str] = Field(min_length=1)
    required_connectors: list[str] = Field(default_factory=list)
    side_effect_level: SideEffectLevel
    approval_level: ApprovalLevel
    claim_latch_policy: str = Field(min_length=1)
    memory_writable: bool = False

    @field_validator("intents", "trigger_phrases")
    @classmethod
    def validate_terms(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("capability terms must not be empty")
        return values


class AssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    requested_capability: str | None = Field(default=None, min_length=1)


class AssistantContext(BaseModel):
    memory_ids: list[str] = Field(default_factory=list)
    qa_baseline_ids: list[str] = Field(default_factory=list)
    user_preferences: dict[str, Any] = Field(default_factory=dict)
    memory_context: str = "{}"
    conversation_id: str = "desktop-default"
    conversation_turns: list[dict[str, str]] = Field(default_factory=list)


class ResponseVerification(BaseModel):
    """Verification receipt attached to every EEEE assistant response."""

    decision: Literal["PASS", "WARN", "BLOCKED"]
    reason: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    claim_latch_receipt_id: str | None = None
    claim_latch_report_id: str | None = None


class CapabilityPlan(BaseModel):
    capability_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
    side_effect_level: SideEffectLevel
    requires_approval: bool


class CapabilityResult(BaseModel):
    capability_id: str = Field(min_length=1)
    status: Literal["completed", "planned", "awaiting_configuration", "blocked", "failed"]
    summary: str = Field(min_length=1)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    memory_candidate_ids: list[str] = Field(default_factory=list)


class CapabilityCandidate(BaseModel):
    capability_id: str = Field(min_length=1)
    score: int = Field(ge=0)
    reasons: list[str] = Field(default_factory=list)


class CapabilitySelection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: SelectionStatus
    capability_id: str | None = None
    candidates: list[CapabilityCandidate] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    required_plugin_id: str | None = Field(default=None, alias="requiredPluginId")
    required_plugin_name: str | None = Field(default=None, alias="requiredPluginName")
    required_plugin_permissions: list[str] = Field(default_factory=list, alias="requiredPluginPermissions")
    suggested_action: str | None = Field(default=None, alias="suggestedAction")
