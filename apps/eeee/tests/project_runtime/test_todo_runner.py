import json

import pytest

from app.project_runtime.scaffold import create_todo_scaffold
from app.project_runtime.todo_runner import TodoProjectRunner


def _claim(decision="PASS"):
    return {
        "decision": decision,
        "receiptId": "receipt-todo-1" if decision == "PASS" else None,
        "claimLatchReportId": "report-todo-1",
    }


def test_todo_runner_writes_independent_qa_and_release_manifest(tmp_path) -> None:
    workspace = tmp_path / "todo-project"
    create_todo_scaffold(workspace)

    result = TodoProjectRunner().run(
        project_id="project-todo",
        project_revision="rev-1",
        workspace=workspace,
        claim_latch=_claim(),
    )

    assert result.status == "PASS"
    assert result.qa_report_path == str(workspace / "QA_REPORT.json")
    assert result.release_manifest_path == str(workspace / "RELEASE_MANIFEST.json")
    assert result.git_branch == "project/project-todo"
    assert result.git_commit and len(result.git_commit) == 40
    assert (workspace / ".git").is_dir()
    qa = json.loads((workspace / "QA_REPORT.json").read_text(encoding="utf-8"))
    assert qa["independent"] is True
    assert qa["status"] == "PASS"
    assert qa["checks"]
    manifest = json.loads((workspace / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["decision"] == "PASS"


def test_todo_runner_blocks_release_without_claimlatch_pass(tmp_path) -> None:
    workspace = tmp_path / "todo-project"
    create_todo_scaffold(workspace)

    result = TodoProjectRunner().run(
        project_id="project-todo",
        project_revision="rev-1",
        workspace=workspace,
        claim_latch=_claim("WARN"),
    )

    assert result.status == "BLOCKED"
    assert result.release_manifest_path is None
    qa = json.loads((workspace / "QA_REPORT.json").read_text(encoding="utf-8"))
    assert qa["status"] == "PASS"
    assert "ClaimLatch" in result.reason
    assert not (workspace / "RELEASE_MANIFEST.json").exists()


def test_todo_runner_fails_closed_when_scaffold_is_incomplete(tmp_path) -> None:
    workspace = tmp_path / "todo-project"
    workspace.mkdir()
    (workspace / "index.html").write_text("<html>", encoding="utf-8")

    with pytest.raises(ValueError, match="Todo scaffold verification failed"):
        TodoProjectRunner().run(
            project_id="project-todo",
            project_revision="rev-1",
            workspace=workspace,
            claim_latch=_claim(),
        )


def test_todo_runner_records_acceptance_criteria_against_qa_evidence(tmp_path) -> None:
    workspace = tmp_path / "todo-project"
    create_todo_scaffold(workspace)

    prepared = TodoProjectRunner().prepare(
        project_id="project-todo",
        project_revision="rev-1",
        workspace=workspace,
        acceptance_criteria=["Todo를 추가할 수 있음"],
    )

    trace = prepared.qa_report["requirementTraceability"]
    assert trace[0]["criterion"] == "Todo를 추가할 수 있음"
    assert trace[0]["status"] == "verified"
    assert trace[0]["evidenceIds"] == prepared.qa_report["evidenceIds"]
