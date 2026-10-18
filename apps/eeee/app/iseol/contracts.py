"""Versioned contracts shared by ISEOL intake, planning, and execution."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import RequestBrief


ProjectType = Literal["web_app", "todo_app", "static_app", "unknown"]
RiskLevel = Literal["low", "medium", "high"]
ExternalActionStatus = Literal["planned", "awaiting_approval", "blocked", "completed"]


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    required: bool = True


class ExternalAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    description: str = Field(min_length=1)
    status: ExternalActionStatus = "planned"
    requires_approval: bool = Field(default=True, alias="requiresApproval")


class ProjectIntent(BaseModel):
    """The single canonical representation of a natural-language project request."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: Literal["iseol-project-intent.v1"] = Field(
        default="iseol-project-intent.v1", alias="schemaVersion"
    )
    raw_text: str = Field(min_length=1, alias="rawText")
    goal: str = Field(min_length=1)
    project_type: ProjectType = Field(alias="projectType")
    template_id: str | None = Field(default=None, alias="templateId")
    target_audience: str = Field(default="개인 사용자", alias="targetAudience")
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list, alias="acceptanceCriteria")
    risk_level: RiskLevel = Field(default="low", alias="riskLevel")
    requires_external_approval: bool = Field(default=False, alias="requiresExternalApproval")
    external_actions: list[ExternalAction] = Field(default_factory=list, alias="externalActions")

    def to_request_brief(self, *, questions: list[ClarificationQuestion] | None = None) -> RequestBrief:
        """Project the canonical intent into the legacy EEEE request contract."""

        target_type = self.project_type
        runtime_profile = "web_app" if self.project_type in {"web_app", "todo_app"} else "static_app"
        questions = questions or []
        return RequestBrief(
            raw_text=self.raw_text,
            goal=self.goal,
            target_type=target_type,
            constraints=list(self.constraints),
            acceptance_criteria=list(self.acceptance_criteria),
            needs_confirmation=bool(questions),
            uncertainties=[question.reason for question in questions],
            canonical_intent=(
                f"project.create.{target_type}"
                if target_type != "unknown"
                else "project.unknown"
            ),
            runtime_profile=runtime_profile,
        )


class IntakeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    intent: ProjectIntent
    questions: list[ClarificationQuestion] = Field(default_factory=list)
    ready: bool


class ProjectExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: Literal["iseol-project-plan.v1"] = Field(
        default="iseol-project-plan.v1", alias="schemaVersion"
    )
    project_id: str = Field(min_length=1, alias="projectId")
    project_revision: str = Field(min_length=1, alias="projectRevision")
    request_id: str = Field(min_length=1, alias="requestId")
    intent: ProjectIntent
    phases: list[str] = Field(default_factory=list)
    tasks: list[dict[str, object]] = Field(default_factory=list)
    selected_extensions: list[str] = Field(default_factory=list, alias="selectedExtensions")
    missing_extensions: list[str] = Field(default_factory=list, alias="missingExtensions")
    external_actions: list[ExternalAction] = Field(default_factory=list, alias="externalActions")
