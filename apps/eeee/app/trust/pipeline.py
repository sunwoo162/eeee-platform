"""One revision-aware trust boundary for claims, releases, and memory."""

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import ExecutionEnvelope
from app.activity.models import ActivityEvent
from app.activity.store import ActivityLedger
from app.integrations.claimlatch_audit import ClaimLatchAuditStore
from app.integrations.contracts import ProjectOutcomeReportV1
from app.trust.gate import TrustGate


PipelineDecision = Literal["PASS", "WARN", "BLOCKED"]


class TrustPipelineDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: PipelineDecision
    reason: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    project_revision: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    claim_latch_receipt_id: str | None = None
    claim_latch_report_id: str | None = None
    qa_report_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class TrustPipeline:
    """Compose ClaimLatch, deterministic QA, release, and memory decisions."""

    def __init__(
        self,
        trust_gate: TrustGate,
        *,
        audit_store: ClaimLatchAuditStore | None = None,
        activity: ActivityLedger | None = None,
    ) -> None:
        self.trust_gate = trust_gate
        self.audit_store = audit_store
        self.activity = activity
        if self.audit_store is not None:
            self.audit_store.init()

    def verify_claim(self, envelope: ExecutionEnvelope) -> TrustPipelineDecision:
        return self._from_check(
            envelope,
            self.trust_gate.verify_claim(
                subject_id=envelope.execution_id,
                project_id=self._project_id(envelope),
                project_revision=self._revision(envelope),
                claim=self._claim(envelope),
                action="pipeline.verify_claim",
            ),
        )

    def verify_action(
        self,
        envelope: ExecutionEnvelope,
        *,
        action: str,
        payload: Mapping[str, object] | None = None,
    ) -> TrustPipelineDecision:
        return self._from_check(
            envelope,
            self.trust_gate.verify_action(
                subject_id=envelope.execution_id,
                project_id=self._project_id(envelope),
                project_revision=self._revision(envelope),
                action=action,
                payload=payload,
            ),
        )

    def verify_agent_result(
        self,
        envelope: ExecutionEnvelope,
        *,
        agent_id: str,
        role: str,
        summary: str,
        evidence_ids: list[str],
        changed_files: list[str] | None = None,
    ) -> TrustPipelineDecision:
        """Verify one specialist handoff before another agent may consume it."""

        prepared = envelope.model_copy(update={"evidence_ids": tuple(evidence_ids)})
        decision = self.verify_action(
            prepared,
            action=f"agent.{agent_id}.handoff",
            payload={
                "agentId": agent_id,
                "role": role,
                "summary": summary,
                "changedFiles": list(changed_files or []),
                "evidenceIds": list(evidence_ids),
            },
        )
        status = "completed" if decision.decision == "PASS" else "blocked"
        self._record_activity(
            ActivityEvent(
                eventType="agent.completed",
                projectId=decision.project_id,
                projectRevision=decision.project_revision,
                runId=envelope.execution_id,
                nodeId=f"agent:{agent_id}",
                actorType="agent",
                actorId=agent_id,
                summary=summary,
                reason=decision.reason,
                selectedBecause="Agent handoff requires ClaimLatch verification before dependency release",
                inputs=[envelope.execution_id],
                outputs=list(changed_files or []),
                evidenceRefs=list(evidence_ids),
                status=status,
                occurredAt=datetime.now(timezone.utc),
            )
        )
        return decision

    def release_gate(
        self,
        envelope: ExecutionEnvelope,
        qa_report: Mapping[str, object] | None,
    ) -> TrustPipelineDecision:
        decision = self.verify_action(envelope, action="release", payload={"qaReport": dict(qa_report or {})})
        qa_failure = _qa_failure(qa_report, envelope)
        if decision.decision != "PASS":
            reason = f"Release requires ClaimLatch PASS: {decision.reason}"
            if qa_failure:
                reason += f"; {qa_failure}"
            result = decision.model_copy(update={"decision": "BLOCKED", "reason": reason,
                                                 "qa_report_id": _string(qa_report, "id")})
        elif qa_failure:
            result = decision.model_copy(update={"decision": "BLOCKED", "reason": qa_failure,
                                                 "qa_report_id": _string(qa_report, "id")})
        else:
            combined_evidence = _unique([
                *decision.evidence_ids,
                *_strings(qa_report, "evidenceIds"),
            ])
            if not combined_evidence:
                result = decision.model_copy(update={
                    "decision": "BLOCKED",
                    "reason": "Release requires verified evidence IDs",
                    "qa_report_id": _string(qa_report, "id"),
                })
            else:
                result = decision.model_copy(update={
                    "qa_report_id": _string(qa_report, "id"),
                    "evidence_ids": combined_evidence,
                })
        if result is None:
            raise AssertionError("release gate did not produce a decision")
        self._record_release_activity(envelope, result, qa_report)
        return result

    def memory_promotion_gate(
        self,
        outcome: ProjectOutcomeReportV1,
        envelope: ExecutionEnvelope,
        qa_report: Mapping[str, object] | None,
    ) -> TrustPipelineDecision:
        project_id = self._project_id(envelope)
        revision = self._revision(envelope)
        base = dict(project_id=project_id, project_revision=revision,
                    subject_id=envelope.execution_id, evidence_ids=list(envelope.evidence_ids))
        if outcome.project_id != project_id or outcome.project_revision != revision:
            return TrustPipelineDecision(decision="BLOCKED", reason="Outcome identity does not match execution",
                                         **base)
        if not _is_pass(outcome.deterministic_verification.get("status")):
            return TrustPipelineDecision(decision="BLOCKED", reason="Deterministic verification did not PASS",
                                         **base)
        reports = outcome.claim_latch_reports
        if not reports or any(not _is_pass(item.get("decision")) for item in reports):
            return TrustPipelineDecision(decision="BLOCKED", reason="Every ClaimLatch report must be PASS",
                                         **base)
        release = self.release_gate(envelope, qa_report)
        if release.decision != "PASS":
            return release.model_copy(update={"reason": f"Memory promotion blocked: {release.reason}"})
        result = release.model_copy(update={"reason": "Outcome passed ClaimLatch, QA, evidence, and release gates"})
        self._record_activity(
            ActivityEvent(
                eventType="memory.promotion.checked",
                projectId=project_id,
                projectRevision=revision,
                runId=envelope.execution_id,
                nodeId=f"memory:{project_id}",
                parentNodeId=f"qa:{project_id}",
                actorType="system",
                actorId="Memory Promotion Gate",
                summary="Memory promotion gate passed",
                reason=result.reason,
                selectedBecause="Deterministic verification, ClaimLatch, independent QA, release, and evidence gates all passed",
                inputs=[envelope.execution_id, *[str(item.get("id")) for item in outcome.claim_latch_reports if item.get("id")]],
                outputs=["memory.promotion.allowed"],
                evidenceRefs=_unique([*result.evidence_ids, *[str(item.get("id")) for item in outcome.claim_latch_reports if item.get("id")], _string(qa_report, "id") or ""]),
                status="completed",
                occurredAt=datetime.now(timezone.utc),
            )
        )
        return result

    def _record_release_activity(
        self,
        envelope: ExecutionEnvelope,
        decision: TrustPipelineDecision,
        qa_report: Mapping[str, object] | None,
    ) -> None:
        qa_id = _string(qa_report, "id")
        qa_evidence = _strings(qa_report, "evidenceIds")
        common_evidence = _unique([*decision.evidence_ids, *qa_evidence, *(item for item in (qa_id, decision.claim_latch_report_id, decision.claim_latch_receipt_id) if item)])
        status = "completed" if decision.decision == "PASS" else "blocked"
        self._record_activity(
            ActivityEvent(
                eventType="claimlatch.checked",
                projectId=decision.project_id,
                projectRevision=decision.project_revision,
                runId=envelope.execution_id,
                nodeId=f"claimlatch:{decision.project_id}",
                actorType="system",
                actorId="ClaimLatch",
                summary=f"ClaimLatch release check {decision.decision}",
                reason=decision.reason,
                selectedBecause="Release cannot proceed without a revision-matched ClaimLatch decision",
                inputs=[envelope.execution_id],
                outputs=[decision.claim_latch_report_id or "claimlatch.decision"],
                evidenceRefs=common_evidence,
                status=status,
                occurredAt=datetime.now(timezone.utc),
            )
        )
        self._record_activity(
            ActivityEvent(
                eventType="qa.completed",
                projectId=decision.project_id,
                projectRevision=decision.project_revision,
                runId=envelope.execution_id,
                nodeId=f"qa:{decision.project_id}",
                parentNodeId=f"claimlatch:{decision.project_id}",
                actorType="system",
                actorId="ISEOL.QA",
                summary=f"Independent QA check {decision.decision}",
                reason=decision.reason if decision.decision != "PASS" else "Independent QA and release prerequisites passed",
                selectedBecause="QA is evaluated independently before release or memory promotion",
                inputs=[qa_id or "qa.report"],
                outputs=["release.gate"],
                evidenceRefs=common_evidence,
                status=status,
                occurredAt=datetime.now(timezone.utc),
            )
        )

    def _record_activity(self, event: ActivityEvent) -> None:
        if self.activity is not None:
            try:
                self.activity.append(event)
            except KeyError:
                # An outcome for an unknown project is still rejected by the
                # trust gate. There is no valid project revision to which an
                # activity event could be attached, so preserve that original
                # rejection instead of masking it with a ledger lookup error.
                return

    def _from_check(self, envelope: ExecutionEnvelope, check) -> TrustPipelineDecision:
        return TrustPipelineDecision(
            decision=check.decision,
            reason=check.reason,
            project_id=self._project_id(envelope),
            project_revision=self._revision(envelope),
            subject_id=envelope.execution_id,
            claim_latch_receipt_id=check.receipt_id or envelope.claim_latch_receipt_id,
            claim_latch_report_id=check.report_id,
            evidence_ids=list(envelope.evidence_ids),
        )

    @staticmethod
    def _project_id(envelope: ExecutionEnvelope) -> str:
        if envelope.project_id is None:
            raise ValueError("Trust pipeline requires a project-bound execution")
        return envelope.project_id

    @staticmethod
    def _revision(envelope: ExecutionEnvelope) -> str:
        if envelope.project_revision is None:
            raise ValueError("Trust pipeline requires a project revision")
        return envelope.project_revision

    @staticmethod
    def _claim(envelope: ExecutionEnvelope) -> str:
        for value in (envelope.output, envelope.input):
            if isinstance(value, Mapping):
                for key in ("claim", "summary", "text", "goal"):
                    item = value.get(key)
                    if isinstance(item, str) and item.strip():
                        return item
        return f"Execution {envelope.execution_id} produced a result"


def _qa_failure(qa_report: Mapping[str, object] | None, envelope: ExecutionEnvelope) -> str | None:
    if not isinstance(qa_report, Mapping):
        return "Independent QA report is missing"
    if not isinstance(qa_report.get("projectId"), str) or not str(qa_report["projectId"]).strip():
        return "QA report project identity is missing"
    if qa_report.get("projectId") != envelope.project_id:
        return "QA report project identity does not match execution"
    if not isinstance(qa_report.get("projectRevision"), str) or not str(qa_report["projectRevision"]).strip():
        return "QA report project revision is missing"
    if qa_report.get("projectRevision") != envelope.project_revision:
        return "QA report is stale for the execution revision"
    if not _is_pass(qa_report.get("status")):
        return "Independent QA did not PASS"
    if qa_report.get("independent") is not True:
        return "QA report is not independent"
    checks = qa_report.get("checks")
    if not isinstance(checks, list) or not checks or any(
        not isinstance(item, Mapping)
        or (
            str(item.get("status", "")).lower() not in {"passed", "skipped"}
            and not (
                item.get("name") == "browser:ui-e2e"
                and str(item.get("status", "")).lower() == "not_run"
            )
        )
        for item in checks
    ):
        return "QA report has no deterministic passing checks"
    return None


def _is_pass(value: object) -> bool:
    return str(value or "").strip().upper() in {"PASS", "PASSED"}


def _string(value: Mapping[str, object] | None, key: str) -> str | None:
    item = value.get(key) if isinstance(value, Mapping) else None
    return item if isinstance(item, str) and item.strip() else None


def _strings(value: Mapping[str, object] | None, key: str) -> list[str]:
    item = value.get(key) if isinstance(value, Mapping) else None
    return [value for value in item if isinstance(value, str) and value.strip()] if isinstance(item, list) else []


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
