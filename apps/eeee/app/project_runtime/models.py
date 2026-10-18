from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ConnectorState = Literal[
    "planned",
    "ready",
    "awaiting_configuration",
    "completed",
    "blocked",
]
ProvisioningStatus = Literal["ready", "awaiting_configuration", "blocked"]
DocumentSyncStatus = Literal["synced", "unchanged", "awaiting_configuration", "blocked"]
EvidenceIngestionStatus = Literal["accepted", "duplicate", "blocked"]


class ConnectorBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    connector_id: str = Field(min_length=1, alias="connectorId")
    state: ConnectorState
    intent: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, alias="idempotencyKey")
    external_ref: str | None = Field(default=None, alias="externalRef")
    reason: str | None = None


class ProjectProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: int = 1
    project_id: str = Field(min_length=1, alias="projectId")
    project_revision: str = Field(min_length=1, alias="projectRevision")
    goal: str = Field(min_length=1)
    template_id: str | None = Field(default=None, alias="templateId")
    assumptions: list[str] = Field(default_factory=list)
    quality_report_path: str | None = Field(default=None, alias="qualityReportPath")
    runtime_profile: Literal["static_app", "web_app", "mobile_app"] = Field(default="static_app", alias="runtimeProfile")
    scope: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list, alias="acceptanceCriteria")
    workspace: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    schedule: dict[str, Any] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    memory_ids: list[str] = Field(default_factory=list)
    qa_baseline_ids: list[str] = Field(default_factory=list)
    connectors: list[ConnectorBinding] = Field(default_factory=list)
    provenance: dict[str, str] = Field(default_factory=dict)

    @field_validator("project_id", "project_revision", "goal", "workspace")
    @classmethod
    def validate_identity_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project identity and goal values must not be empty")
        return value

    @property
    def provisioning_status(self) -> ProvisioningStatus:
        states = {binding.state for binding in self.connectors}
        if "blocked" in states:
            return "blocked"
        if "awaiting_configuration" in states or "planned" in states:
            return "awaiting_configuration"
        return "ready"

    def connector(self, connector_id: str) -> ConnectorBinding:
        for binding in self.connectors:
            if binding.connector_id == connector_id:
                return binding
        raise KeyError(f"Connector not found in project profile: {connector_id}")


class ProjectProvisioningResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    profile: ProjectProfile
    missing_connectors: list[str] = Field(default_factory=list)
    execution_plan_path: str | None = Field(default=None, alias="executionPlanPath")
    qa_report_path: str | None = Field(default=None, alias="qaReportPath")
    release_manifest_path: str | None = Field(default=None, alias="releaseManifestPath")

    @property
    def status(self) -> ProvisioningStatus:
        return self.profile.provisioning_status


class ProjectDocumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    project_id: str = Field(min_length=1, alias="projectId")
    provider: Literal["notion"]
    project_revision: str = Field(min_length=1, alias="projectRevision")
    external_id: str = Field(min_length=1, alias="externalId")
    external_url: str | None = Field(default=None, alias="externalUrl")
    content_hash: str = Field(min_length=1, alias="contentHash")
    synced_at: datetime = Field(alias="syncedAt")


class ProjectDocumentSyncResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: DocumentSyncStatus
    project_id: str = Field(min_length=1, alias="projectId")
    provider: Literal["notion"]
    revision: str = Field(min_length=1)
    document: ProjectDocumentRecord | None = None
    trust: Any | None = None
    reason: str | None = None


class ProjectEvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    project_id: str = Field(min_length=1, alias="projectId")
    evidence_type: Literal["github-review"] = Field(alias="evidenceType")
    project_revision: str = Field(min_length=1, alias="projectRevision")
    reference: str = Field(min_length=1)
    content_hash: str = Field(min_length=1, alias="contentHash")
    payload: dict[str, Any]
    created_at: datetime = Field(alias="createdAt")


class ProjectEvidenceIngestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: EvidenceIngestionStatus
    evidence: ProjectEvidenceRecord | None = None
    trust: Any | None = None
    reason: str | None = None

