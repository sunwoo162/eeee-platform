from datetime import datetime, timezone

import httpx

from app.contracts import ExecutionEnvelope, ExecutionStatus
from app.integrations.claimlatch_audit import ClaimLatchAuditStore
from app.integrations.claimlatch_client import ClaimLatchClient
from app.integrations.contracts import ProjectOutcomeReportV1
from app.trust.gate import TrustGate
from app.trust.pipeline import TrustPipeline


def _response(decision: str) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "subjectId": "execution-1",
        "projectId": "project-1",
        "projectRevision": "rev-1",
        "subjectType": "claim",
        "claims": [],
        "evidence": [{"id": "evidence-1"}],
        "deterministicChecks": [],
        "decision": decision,
        "claimLatchReportId": "claim-report-1",
        "receiptId": "receipt-1",
        "createdAt": "2026-10-07T00:00:00Z",
    }


def _envelope() -> ExecutionEnvelope:
    return ExecutionEnvelope(
        execution_id="execution-1", request_id="request-1", project_id="project-1",
        project_revision="rev-1", capability_id="project-execution", tool_id="iseol",
        actor="ISEOL", status=ExecutionStatus.RUNNING, evidence_ids=("evidence-1",),
    )


def _pipeline(tmp_path, decision="PASS", *, current_revision="rev-1") -> TrustPipeline:
    audits = ClaimLatchAuditStore(tmp_path / "audit.sqlite3")
    client = ClaimLatchClient(
        "http://claimlatch.local",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=_response(decision))),
        audit_store=audits,
        current_revision_resolver=lambda _project_id: current_revision,
    )
    return TrustPipeline(
        TrustGate(client, current_revision_resolver=lambda _project_id: current_revision),
        audit_store=audits,
    )


def _qa(*, status="PASS", independent=True, project_id="project-1", revision="rev-1", browser_status=None):
    checks = [{"status": "passed"}]
    if browser_status is not None:
        checks.append({"name": "browser:ui-e2e", "status": browser_status, "evidenceId": "browser-evidence"})
    return {
        "id": "qa-report-1", "status": status, "independent": independent,
        "projectId": project_id, "projectRevision": revision,
        "evidenceIds": ["evidence-1", "browser-evidence"] if browser_status else ["evidence-1"],
        "checks": checks,
    }


def _outcome():
    return ProjectOutcomeReportV1.model_validate({
        "schemaVersion": 1, "projectId": "project-1", "requestId": "request-1",
        "projectRevision": "rev-1", "status": "completed", "artifacts": [{"id": "artifact-1"}],
        "agentTeams": [], "handoffs": [],
        "deterministicVerification": {"status": "PASS"}, "qaReport": _qa(),
        "claimLatchReports": [{"id": "claim-report-1", "decision": "PASS",
                                "projectId": "project-1", "projectRevision": "rev-1"}],
        "receipts": [{"id": "receipt-1"}], "risks": [], "memoryCandidates": [],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    })


def test_verify_claim_returns_structured_pass_and_persists_receipt(tmp_path):
    pipeline = _pipeline(tmp_path)

    decision = pipeline.verify_claim(_envelope())

    assert decision.decision == "PASS"
    assert decision.project_revision == "rev-1"
    assert decision.claim_latch_receipt_id == "receipt-1"
    assert decision.claim_latch_report_id == "claim-report-1"
    assert decision.evidence_ids == ["evidence-1"]
    assert pipeline.audit_store.get_for_verification("project-1", "execution-1", "rev-1").decision == "PASS"


def test_missing_claimlatch_warns_but_release_and_memory_cannot_pass(tmp_path):
    pipeline = TrustPipeline(TrustGate(None, mode="advisory"))
    envelope = _envelope()

    claim = pipeline.verify_claim(envelope)
    release = pipeline.release_gate(envelope, _qa())
    memory = pipeline.memory_promotion_gate(_outcome(), envelope, _qa())

    assert claim.decision == "WARN"
    assert release.decision == "BLOCKED"
    assert memory.decision == "BLOCKED"


def test_stale_revision_blocks_claim_before_adapter(tmp_path):
    pipeline = _pipeline(tmp_path, current_revision="rev-2")

    decision = pipeline.verify_claim(_envelope())

    assert decision.decision == "BLOCKED"
    assert "stale" in decision.reason.lower()


def test_non_pass_claimlatch_and_failed_qa_block_release(tmp_path):
    pipeline = _pipeline(tmp_path, decision="WARN")

    result = pipeline.release_gate(_envelope(), _qa(status="FAIL"))

    assert result.decision == "BLOCKED"
    assert "PASS" in result.reason


def test_not_applicable_browser_check_can_pass_release_gate(tmp_path):
    pipeline = _pipeline(tmp_path)

    result = pipeline.release_gate(
        _envelope(),
        _qa(browser_status="not_applicable"),
    )

    assert result.decision == "PASS"


def test_mismatched_identity_and_missing_evidence_block_memory_promotion(tmp_path):
    pipeline = _pipeline(tmp_path)
    outcome = _outcome()
    bad_qa = _qa(project_id="other-project")

    result = pipeline.memory_promotion_gate(outcome, _envelope(), bad_qa)

    assert result.decision == "BLOCKED"
    assert "identity" in result.reason.lower() or "project" in result.reason.lower()
