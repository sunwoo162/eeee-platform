from datetime import datetime, timezone

from app.contracts import ExecutionEnvelope, ExecutionStatus
from app.trust.pipeline import _qa_failure


def _envelope() -> ExecutionEnvelope:
    started = datetime.now(timezone.utc)
    return ExecutionEnvelope(
        execution_id="execution-1",
        request_id="request-1",
        project_id="project-1",
        project_revision="revision-1",
        capability_id="project-execution",
        tool_id="iseol",
        actor="assistant",
        status=ExecutionStatus.COMPLETED,
        output={"status": "completed"},
        started_at=started,
        completed_at=started,
    )


def _passing_report() -> dict[str, object]:
    return {
        "id": "qa-1",
        "projectId": "project-1",
        "projectRevision": "revision-1",
        "status": "PASS",
        "independent": True,
        "checks": [{"status": "passed"}],
    }


def test_qa_report_must_include_project_identity() -> None:
    report = _passing_report()
    report.pop("projectId")

    assert _qa_failure(report, _envelope()) == "QA report project identity is missing"


def test_qa_report_must_include_project_revision() -> None:
    report = _passing_report()
    report.pop("projectRevision")

    assert _qa_failure(report, _envelope()) == "QA report project revision is missing"

