from enum import Enum

from pydantic import BaseModel, Field


class RequestBrief(BaseModel):
    raw_text: str = Field(min_length=1)
    goal: str
    target_type: str
    constraints: list[str]
    acceptance_criteria: list[str]
    needs_confirmation: bool = False
    uncertainties: list[str] = Field(default_factory=list)
    canonical_intent: str = "project.unknown"
    runtime_profile: str = "static_app"


class RepositorySnapshot(BaseModel):
    full_name: str
    html_url: str
    description: str
    stars: int
    forks: int
    open_issues: int
    license_spdx: str | None
    default_branch: str
    pushed_at: str
    topics: list[str]


class CandidateScore(BaseModel):
    repository: RepositorySnapshot
    total: float
    dimension_scores: dict[str, float]
    evidence: list[str]
    risks: list[str]
    status: str


class Decision(BaseModel):
    request_id: str
    selected: list[str]
    alternatives: list[str]
    approved: bool
    notes: str


class Run(BaseModel):
    id: str
    request_id: str
    status: str
    workspace: str
    events: list[dict[str, object]]
    artifacts: list[dict[str, object]]
    error: str | None = None
    created_at: str | None = None


class RequestSnapshot(BaseModel):
    request_id: str
    project_id: str
    brief: RequestBrief
    workspace: str
    candidates: list[CandidateScore] = Field(default_factory=list)
    decision: Decision | None = None
    decision_events: list[dict[str, object]] = Field(default_factory=list)
    runs: list[Run] = Field(default_factory=list)


class PetState(str, Enum):
    idle = "idle"
    researching = "researching"
    awaiting_approval = "awaiting_approval"
    working = "working"
    verifying = "verifying"
    completed = "completed"
    blocked = "blocked"
    failed = "failed"


class Project(BaseModel):
    id: str
    name: str
    workspace: str
    revision: str
    state: PetState
    active_task_id: str | None
    user_id: str = "local-user"


class TaskRecord(BaseModel):
    id: str
    project_id: str
    request_id: str
    state: PetState
    message: str
    required_action: str | None
    revision: str
    report_id: str | None
    report: dict[str, object] | None


class ReportRecord(BaseModel):
    id: str
    project_id: str
    task_id: str
    revision: str
    status: str
    summary: str
    checks: list[dict[str, object]]


class PetViewModel(BaseModel):
    state: PetState
    message: str
    task_id: str | None
    request_id: str | None
    required_action: str | None
    candidates: list[CandidateScore] = Field(default_factory=list)
    latest_event: dict[str, object] | None
    report: dict[str, object] | None
    workspace: str | None
