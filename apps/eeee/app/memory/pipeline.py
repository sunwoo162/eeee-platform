from __future__ import annotations

from collections.abc import Iterable

from app.domain.errors import ApprovalError
from app.integrations.contracts import ProjectOutcomeReportV1
from app.memory.compiler import MemoryCompiler
from app.memory.models import MemoryRecord
from app.memory.store import MemoryStore


class MemoryIngestError(ApprovalError):
    """A project outcome has not satisfied every release-memory gate."""


class OutcomeMemoryPipeline:
    """Convert only independently verified outcomes into EEEE memory candidates."""

    def __init__(
        self,
        store: MemoryStore,
        compiler: MemoryCompiler | None = None,
    ) -> None:
        self.store = store
        self.compiler = compiler or MemoryCompiler()
        self.store.init()

    def ingest(
        self, report: ProjectOutcomeReportV1, *, user_id: str = "local-user"
    ) -> list[MemoryRecord]:
        failures = list(_gate_failures(report))
        if failures:
            raise MemoryIngestError("Cannot ingest project outcome into memory: " + "; ".join(failures))

        candidates = self.compiler.compile(report)
        return [
            self.store.save_candidate(candidate.model_copy(update={"user_id": user_id}))
            for candidate in candidates
        ]


def _gate_failures(report: ProjectOutcomeReportV1) -> Iterable[str]:
    if report.status != "completed":
        yield "project status is not completed"
    if not _is_pass(report.deterministic_verification.get("status")):
        yield "deterministic verification did not pass"

    qa = report.qa_report
    if not _is_pass(qa.get("status")):
        yield "independent QA did not pass"
    if qa.get("independent") is not True:
        yield "QA report is not marked independent"
    checks = qa.get("checks")
    if not isinstance(checks, list) or not checks or any(
        not isinstance(check, dict)
        or str(check.get("status", "")).strip().lower() not in {"passed", "skipped"}
        for check in checks
    ):
        yield "QA report has no deterministic passing checks"
    if qa.get("projectId") and qa.get("projectId") != report.project_id:
        yield "QA report belongs to a different project"
    if qa.get("projectRevision") and qa.get("projectRevision") != report.project_revision:
        yield "QA report is stale for the outcome revision"

    if report.memory_candidates and not report.claim_latch_reports:
        yield "memory candidates have no ClaimLatch report"
    for claim_latch_report in report.claim_latch_reports:
        if not _is_pass(claim_latch_report.get("decision")):
            yield "a ClaimLatch report is not PASS"
        report_id = claim_latch_report.get("id") or claim_latch_report.get("claimLatchReportId")
        if not str(report_id or "").strip():
            yield "a ClaimLatch report has no stable id"
        if claim_latch_report.get("projectId") and claim_latch_report.get("projectId") != report.project_id:
            yield "ClaimLatch report belongs to a different project"
        if (
            claim_latch_report.get("projectRevision")
            and claim_latch_report.get("projectRevision") != report.project_revision
        ):
            yield "ClaimLatch report is stale for the outcome revision"


def _is_pass(value: object) -> bool:
    return str(value or "").strip().upper() in {"PASS", "PASSED"}
