"""Deterministic request extraction and work-plan construction."""

import re

from pydantic import BaseModel

from app.domain.models import CandidateScore, RequestBrief


class WorkStep(BaseModel):
    id: str
    title: str
    description: str
    requires_approval: bool
    expected_outputs: list[str]


class WorkPlan(BaseModel):
    steps: list[WorkStep]
    requires_selection: bool


_TARGET_PATTERNS = (
    ("todo_app", re.compile(r"(?:\btodo\b|할\s*일|체크리스트|to\s*do)", re.I)),
    ("local_ai_app", re.compile(r"\b(?:local\s+ai|offline\s+ai)\b", re.I)),
    ("web_app", re.compile(r"(?:\b(?:web\s*app|website|web\s+application)\b|웹(?:\s*(?:앱|프로젝트|서비스))?)", re.I)),
    ("developer_tool", re.compile(r"\b(?:developer\s+(?:cli\s+)?tool|cli|command.line\s+tool)\b", re.I)),
    ("automation", re.compile(r"\b(?:automate|automation|workflow)\b", re.I)),
)
_CONSTRAINT_BOUNDARY = re.compile(r"\s*(?:;\s*|\b(?=using\b|with\b|must\b|should\b))", re.I)
_PLATFORMS = re.compile(r"\b(?:windows|macos|linux|android|ios|browser|cross.platform)\b", re.I)
_VAGUE_GOAL = re.compile(r"^(?:build|make|create)\s+(?:a\s+)?(?:something|anything|app|tool)\.?$", re.I)


def parse_request(text: str) -> RequestBrief:
    """Extract only information present in the request and flag missing details."""
    if not text.strip():
        raise ValueError("Request text cannot be blank")
    normalized = " ".join(text.split())
    parts = [part.strip() for part in _CONSTRAINT_BOUNDARY.split(normalized) if part.strip()]
    goal = parts[0]
    matching_targets = [kind for kind, pattern in _TARGET_PATTERNS if pattern.search(normalized)]
    target_type = matching_targets[0] if len(matching_targets) == 1 else "unknown"
    constraints = parts[1:]
    uncertainties: list[str] = []
    if not matching_targets:
        constraints.insert(0, goal)
        uncertainties.append("Target type needs confirmation")
    elif len(matching_targets) > 1:
        uncertainties.append("Target type is ambiguous: " + ", ".join(matching_targets))
    if _VAGUE_GOAL.fullmatch(goal):
        uncertainties.append("Goal needs clarification")
    if not _PLATFORMS.search(normalized):
        uncertainties.append("Target platform needs confirmation")
    canonical_intent = (
        f"project.create.{matching_targets[0]}"
        if len(matching_targets) == 1
        else "project.unknown"
    )
    return RequestBrief(
        raw_text=text,
        goal=goal,
        target_type=target_type,
        constraints=constraints,
        acceptance_criteria=[
            "Build the requested result and verify the build succeeds",
            "Run tests and report their results",
        ],
        needs_confirmation=bool(uncertainties),
        uncertainties=uncertainties,
        canonical_intent=canonical_intent,
    )


def build_work_plan(brief: RequestBrief, candidates: list[CandidateScore]) -> WorkPlan:
    """Describe the gated path from research to verified implementation."""
    names = list(dict.fromkeys(candidate.repository.full_name for candidate in candidates))
    comparison = (
        f"Compare at least two candidates: {', '.join(names)}"
        if len(names) >= 2
        else "Compare at least two candidates before a selection can be approved"
    )
    steps = []
    if brief.needs_confirmation:
        steps.append(WorkStep(
            id="confirm", title="Confirm request", description="Resolve: " + "; ".join(brief.uncertainties),
            requires_approval=False, expected_outputs=["Confirmed request brief"],
        ))
    steps.extend([
        WorkStep(id="research", title="Research OSS", description=f"Find OSS for {brief.goal}",
                 requires_approval=False, expected_outputs=["Candidate evidence and risks"]),
        WorkStep(id="compare", title="Compare candidates", description=comparison,
                 requires_approval=False, expected_outputs=["Comparison of at least two candidates"]),
        WorkStep(id="approve", title="Approve selection", description="Select candidate(s) and approve the decision",
                 requires_approval=True, expected_outputs=["Approved OSS decision"]),
        WorkStep(id="implement", title="Implement", description=f"Build {brief.goal} in the approved workspace",
                 requires_approval=True, expected_outputs=["Project files and pinned dependencies"]),
        WorkStep(id="verify", title="Verify", description="Run the build and tests against the latest project state",
                 requires_approval=False, expected_outputs=["Build and test results"]),
    ])
    return WorkPlan(steps=steps, requires_selection=len(names) >= 2)
