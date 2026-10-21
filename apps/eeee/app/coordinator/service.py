"""Coordinator-owned project and task state transitions."""

from datetime import datetime, timezone
from uuid import uuid4

from app.coordinator.fake_worker import DeterministicFakeWorker
from app.contracts import ExecutionEnvelope, ExecutionStatus
from app.domain.errors import ApprovalError
from app.domain.models import (
    CandidateScore,
    PetState,
    PetViewModel,
    Project,
    ReportRecord,
    TaskRecord,
)
from app.execution.runner import WorkspaceExecutionBlocked
from app.execution.verifier import WorkspaceVerifier
from app.integrations.contracts import ProjectBriefV1, ProjectOutcomeReportV1
from app.memory.models import MemoryRecord
from app.memory.pipeline import OutcomeMemoryPipeline
from app.memory.store import MemoryStore
from app.oss.github_client import ResearchError
from app.oss.researcher import GitHubResearcher
from app.storage.sqlite import SQLiteStore
from app.trust.gate import TrustGate
from app.trust.pipeline import TrustPipeline
from app.workspace.artifacts import WorkspaceArtifactWriter
from app.workflow.approvals import ApprovalService
from app.workflow.planner import parse_request


class Coordinator:
    def __init__(
        self,
        store: SQLiteStore,
        worker: DeterministicFakeWorker | None = None,
        artifact_writer: WorkspaceArtifactWriter | None = None,
        researcher: GitHubResearcher | None = None,
        verifier: WorkspaceVerifier | None = None,
        memory_store: MemoryStore | None = None,
        trust_gate: TrustGate | None = None,
    ):
        self.store = store
        self.worker = worker or DeterministicFakeWorker()
        self.approvals = ApprovalService(store)
        self.artifacts = artifact_writer or WorkspaceArtifactWriter()
        self.researcher = researcher
        self.verifier = verifier
        self.memory = memory_store or MemoryStore(store.path)
        self.memory_pipeline = OutcomeMemoryPipeline(self.memory)
        self.claimlatch_audits = store.claimlatch_audits
        self.trust_gate = trust_gate
        self.trust_pipeline = (
            TrustPipeline(trust_gate, audit_store=store.claimlatch_audits)
            if trust_gate is not None else None
        )

    def record_project_outcome(
        self, outcome_report: ProjectOutcomeReportV1, *, user_id: str = "local-user"
    ) -> list[MemoryRecord]:
        """Ingest ISEOL's independently verified project result into EEEE memory."""

        try:
            project = self.store.get_project(outcome_report.project_id)
        except KeyError:
            project = None
        if project is not None and project.revision != outcome_report.project_revision:
            raise ApprovalError(
                "Cannot ingest project outcome: stale project revision "
                f"{outcome_report.project_revision}; current is {project.revision}"
            )
        if self.trust_pipeline is not None:
            envelope = ExecutionEnvelope(
                execution_id=f"{outcome_report.project_id}:outcome",
                request_id=outcome_report.request_id,
                project_id=outcome_report.project_id,
                project_revision=outcome_report.project_revision,
                capability_id="project-outcome",
                tool_id="iseol",
                actor="ISEOL",
                status=ExecutionStatus.RUNNING,
                input={"status": outcome_report.status},
                evidence_ids=tuple(
                    item for item in outcome_report.qa_report.get("evidenceIds", [])
                    if isinstance(item, str) and item.strip()
                ),
            )
            trust = self.trust_pipeline.memory_promotion_gate(
                outcome_report, envelope, outcome_report.qa_report
            )
            if trust.decision != "PASS":
                raise ApprovalError(f"ClaimLatch blocked memory promotion: {trust.reason}")
        return self.memory_pipeline.ingest(outcome_report, user_id=user_id)

    def record_verified_project_outcome(
        self,
        outcome_report: ProjectOutcomeReportV1,
        *,
        actor: str = "EEEE Verified Outcome",
        user_id: str = "local-user",
    ) -> list[MemoryRecord]:
        """Persist and activate only an outcome that passed every gate.

        ``record_project_outcome`` intentionally leaves records as candidates
        for the explicit API promotion flow. ISEOL's release path uses this
        method only after the outcome has passed deterministic QA and
        ClaimLatch, so verified patterns become available to the next project.
        """

        records = self.record_project_outcome(outcome_report, user_id=user_id)
        promoted: list[MemoryRecord] = []
        for record in records:
            promoted.append(
                self.memory.promote(
                    record.id,
                    actor=actor,
                    evidence_ids=list(dict.fromkeys([
                        *record.evidence_ids,
                        *record.verification_ids,
                    ])), user_id=user_id,
                )
            )
        return promoted

    def promote_memory(
        self, memory_id: str, *, actor: str, evidence_ids: list[str],
        user_id: str = "local-user"
    ) -> MemoryRecord:
        record = self.memory.get(memory_id, user_id=user_id)
        try:
            project = self.store.get_project(record.source_project_id)
        except KeyError:
            project = None
        if project is not None and self.trust_gate is not None:
            trust = self.trust_gate.verify_action(
                subject_id=f"{memory_id}:promotion",
                project_id=project.id,
                project_revision=project.revision,
                action="memory.promote",
                payload={"memoryId": memory_id, "evidenceIds": list(evidence_ids)},
            )
            if trust.decision != "PASS":
                raise ApprovalError(f"ClaimLatch blocked memory promotion: {trust.reason}")
        return self.memory.promote(
            memory_id, actor=actor, evidence_ids=evidence_ids, user_id=user_id
        )

    def remember_user_preference(
        self, key: str, value: str, *, scope: dict[str, object] | None = None,
        user_id: str = "local-user"
    ) -> MemoryRecord:
        return self.memory.save_user_preference(key, value, scope=scope, user_id=user_id)

    def build_project_brief(
        self, project_id: str, request_id: str, *, user_id: str = "local-user"
    ) -> ProjectBriefV1:
        """Retrieve verified memory before ISEOL decomposes the next project."""

        project = self.store.get_project(project_id)
        request = self.store.get_request(request_id)
        memories = self.memory.search(request.raw_text, user_id=user_id, limit=50)
        memory_ids = [memory.id for memory in memories]
        qa_baseline_ids = [
            memory.id
            for memory in memories
            if memory.kind in {"qa_rule", "regression_rule"}
        ]
        verified_memories = [
            {
                "id": memory.id,
                "kind": memory.kind,
                "content": memory.content,
                "scope": memory.scope,
                "confidence": memory.confidence,
                "verificationIds": memory.verification_ids,
            }
            for memory in memories
        ]
        user_preferences = {
            key: record.content
            for key, record in self.memory.search_user_preferences(user_id=user_id).items()
        }
        return ProjectBriefV1(
            schema_version=1,
            project_id=project.id,
            request_id=request_id,
            user_goal=request.goal,
            scope=[request.target_type, *request.acceptance_criteria],
            constraints=request.constraints,
            preferences={
                "canonicalIntent": request.canonical_intent,
                "verifiedMemories": verified_memories,
                "userPreferences": user_preferences,
            },
            schedule={},
            retrieved_memory_ids=memory_ids,
            qa_baseline_ids=qa_baseline_ids,
            created_at=datetime.now(timezone.utc),
        )

    def create_project(
        self, project_id: str, name: str, workspace: str, revision: str = "initial",
        *, user_id: str = "local-user",
    ) -> Project:
        return self.store.create_project(project_id, name, workspace, revision, user_id=user_id)

    def create_request(self, project_id: str, text: str, *, user_id: str | None = None) -> PetViewModel:
        project = self.store.get_project(project_id, user_id=user_id)
        brief = parse_request(text)
        request_id = self.store.save_request(brief)
        task = self.store.create_task(project.id, request_id, project.revision)
        self.store.append_task_event(
            task.id,
            {"action": "request_created", "actor": "user", "request_id": request_id},
        )
        return self.get_state(project_id)

    def get_state(self, project_id: str, *, user_id: str | None = None) -> PetViewModel:
        project = self.store.get_project(project_id, user_id=user_id)
        if project.active_task_id is None:
            return PetViewModel(
                state=PetState.idle,
                message="Ready for a development request",
                task_id=None,
                request_id=None,
                required_action=None,
                candidates=[],
                latest_event=None,
                report=None,
                workspace=project.workspace,
            )
        task = self.store.get_task(project.active_task_id)
        events = self.store.get_task_events(task.id)
        return PetViewModel(
            state=task.state,
            message=task.message,
            task_id=task.id,
            request_id=task.request_id,
            required_action=task.required_action,
            candidates=self.store.get_candidates(task.request_id),
            latest_event=events[-1] if events else None,
            report=task.report,
            workspace=project.workspace,
        )

    def approve_selection(
        self, project_id: str, request_id: str, selected: list[str], *, user_id: str | None = None
    ) -> PetViewModel:
        project = self.store.get_project(project_id, user_id=user_id)
        task = self._active_task(project)
        if task.request_id != request_id:
            raise ApprovalError("Request does not belong to the active project task")
        if task.state != PetState.awaiting_approval:
            raise ApprovalError("Candidate approval is not required in the current state")
        request = self.store.get_request(request_id)
        candidates = self.store.get_candidates(request_id)
        selected_candidates = [
            candidate for candidate in candidates if candidate.repository.full_name in selected
        ]
        try:
            plan_path = self.artifacts.write_plan(
                project.workspace,
                task.id,
                request_text=request.raw_text,
                revision=task.revision,
                selected=selected_candidates,
            )
        except OSError as exc:
            updated = self.store.update_task(
                task.id,
                PetState.failed,
                f"Could not write the workspace plan: {exc}",
                required_action="retry_task",
            )
            self.store.append_task_event(
                updated.id,
                {"action": "plan_write_failed", "actor": "coordinator"},
            )
            return self.get_state(project_id)
        self.approvals.approve_decision(request_id, selected)
        updated = self.store.update_task(
            task.id,
            PetState.working,
            "Working on the approved selection",
            required_action=None,
        )
        self.store.append_task_event(
            updated.id,
            {
                "action": "selection_approved",
                "actor": "user",
                "selected": list(selected),
                "artifacts": [{"type": "plan", "path": str(plan_path)}],
            },
        )
        return self.get_state(project_id)

    def advance_task(
        self, project_id: str, task_id: str, *, user_id: str | None = None
    ) -> PetViewModel:
        project = self.store.get_project(project_id, user_id=user_id)
        task = self.store.get_task(task_id)
        if task.project_id != project_id or project.active_task_id != task_id:
            raise ApprovalError("Task does not belong to the active project")
        if task.state == PetState.researching:
            try:
                candidates = (
                    self.researcher.research(self.store.get_request(task.request_id))
                    if self.researcher
                    else _demo_candidates()
                )
            except ResearchError as exc:
                updated = self.store.update_task(
                    task.id,
                    PetState.failed,
                    f"GitHub research failed: {exc}",
                    required_action="retry_task",
                )
                self.store.append_task_event(
                    updated.id,
                    {
                        "action": "research_failed",
                        "actor": "coordinator",
                        "recoverable": exc.recoverable,
                        "status_code": exc.status_code,
                    },
                )
                return self.get_state(project_id)
            self.store.save_candidates(task.request_id, candidates)
            updated = self.store.update_task(
                task.id,
                PetState.awaiting_approval,
                "Choose an OSS starting point",
                required_action="approve_selection",
            )
            self.store.append_task_event(
                updated.id,
                {"action": "research_completed", "actor": "coordinator", "candidate_count": len(candidates)},
            )
            return self.get_state(project_id)
        if task.state == PetState.awaiting_approval:
            raise ApprovalError("Approval required before work can continue")
        if task.state in {PetState.working, PetState.verifying}:
            if task.state == PetState.verifying and task.revision != project.revision:
                updated = self.store.update_task(
                    task.id,
                    PetState.blocked,
                    "Project changed since this task started",
                    required_action="retry_task",
                )
                self.store.append_task_event(
                    updated.id,
                    {"action": "stale_revision", "actor": "coordinator", "revision": project.revision},
                )
                return self.get_state(project_id)
            if task.state == PetState.verifying and self.verifier is not None:
                try:
                    verification = self.verifier.verify(project.workspace)
                except WorkspaceExecutionBlocked as exc:
                    updated = self.store.update_task(
                        task.id,
                        PetState.blocked,
                        f"Workspace verification blocked: {exc}",
                        required_action="retry_task",
                    )
                    self.store.append_task_event(
                        updated.id,
                        {
                            "action": "workspace_blocked",
                            "actor": "coordinator",
                            "reason": str(exc),
                        },
                    )
                    return self.get_state(project_id)
                report_payload = verification.as_report_payload()
                if verification.status == "passed":
                    next_state = PetState.completed
                    message = "Verification passed"
                    required_action = None
                else:
                    next_state = PetState.failed
                    message = "Verification failed; retry required"
                    required_action = "retry_task"
            else:
                next_state, message, required_action, report_payload = self.worker.advance(task)
            report_id = None
            report = None
            if report_payload is not None:
                try:
                    verification_path = self.artifacts.write_verification(
                        project.workspace,
                        task.id,
                        status=str(report_payload["status"]),
                        summary=str(report_payload["summary"]),
                        checks=list(report_payload["checks"]),
                    )
                except OSError as exc:
                    updated = self.store.update_task(
                        task.id,
                        PetState.failed,
                        f"Could not write the verification artifact: {exc}",
                        required_action="retry_task",
                    )
                    self.store.append_task_event(
                        updated.id,
                        {"action": "verification_write_failed", "actor": "coordinator"},
                    )
                    return self.get_state(project_id)
                report_id = str(uuid4())
                report = {
                    "id": report_id,
                    "revision": task.revision,
                    **report_payload,
                    "artifacts": [
                        {"type": "verification", "path": str(verification_path)}
                    ],
                }
                report_record = ReportRecord(
                    id=report_id,
                    project_id=project_id,
                    task_id=task.id,
                    revision=task.revision,
                    status=str(report_payload["status"]),
                    summary=str(report_payload["summary"]),
                    checks=list(report_payload["checks"]),
                )
                self.store.save_report(report_record)
            updated = self.store.update_task(
                task.id,
                next_state,
                message,
                required_action=required_action,
                report_id=report_id,
                report=report,
            )
            self.store.append_task_event(
                updated.id,
                {"action": next_state.value, "actor": "coordinator", "revision": updated.revision},
            )
            return self.get_state(project_id)
        if task.state == PetState.completed:
            raise ApprovalError("Task is already completed")
        raise ApprovalError("Task requires retry before it can continue")

    def run_until_checkpoint(
        self, project_id: str, task_id: str, max_steps: int = 10, *, user_id: str | None = None
    ) -> PetViewModel:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        for _ in range(max_steps):
            state = self.get_state(project_id, user_id=user_id)
            if state.task_id != task_id:
                raise ApprovalError("Task does not belong to the active project")
            if state.state not in {PetState.researching, PetState.working, PetState.verifying}:
                return state
            self.advance_task(project_id, task_id)
        return self.get_state(project_id)

    def retry_task(
        self, project_id: str, task_id: str, *, user_id: str | None = None
    ) -> PetViewModel:
        project = self.store.get_project(project_id, user_id=user_id)
        task = self.store.get_task(task_id)
        if task.project_id != project_id or project.active_task_id != task_id:
            raise ApprovalError("Task does not belong to the active project")
        if task.state not in {PetState.blocked, PetState.failed}:
            raise ApprovalError("Only blocked or failed tasks can be retried")
        decision = self.store.get_decision(task.request_id)
        next_state = (
            PetState.working
            if task.state == PetState.failed and decision and decision.approved
            else PetState.researching
        )
        message = (
            "Retrying the approved workspace task"
            if next_state == PetState.working
            else "Rechecking the project before retry"
        )
        updated = self.store.update_task(
            task.id,
            next_state,
            message,
            required_action=None,
            revision=project.revision,
        )
        self.store.append_task_event(
            updated.id,
            {"action": "retry_requested", "actor": "user", "revision": project.revision},
        )
        return self.get_state(project_id)

    def _active_task(self, project: Project) -> TaskRecord:
        if project.active_task_id is None:
            raise ApprovalError("Project has no active task")
        return self.store.get_task(project.active_task_id)


def _demo_candidates() -> list[CandidateScore]:
    return [
        CandidateScore(
            repository={
                "full_name": "demo/alpha",
                "html_url": "https://github.com/demo/alpha",
                "description": "A small web app starter",
                "stars": 1200,
                "forks": 110,
                "open_issues": 12,
                "license_spdx": "MIT",
                "default_branch": "main",
                "pushed_at": "2026-09-20T00:00:00Z",
                "topics": ["web-app", "python"],
            },
            total=82.0,
            dimension_scores={"fit": 38.0, "adoption": 12.0, "maintenance": 14.0, "trust": 13.0, "integration": 5.0},
            evidence=["Demo evidence: web app metadata matches"],
            risks=[],
            status="candidate",
        ),
        CandidateScore(
            repository={
                "full_name": "demo/beta",
                "html_url": "https://github.com/demo/beta",
                "description": "A minimal web app toolkit",
                "stars": 450,
                "forks": 35,
                "open_issues": 8,
                "license_spdx": "Apache-2.0",
                "default_branch": "main",
                "pushed_at": "2026-09-10T00:00:00Z",
                "topics": ["web-app", "toolkit"],
            },
            total=68.0,
            dimension_scores={"fit": 32.0, "adoption": 9.0, "maintenance": 14.0, "trust": 13.0},
            evidence=["Demo evidence: web app topic matches"],
            risks=["Smaller adoption signal"],
            status="uncertain",
        ),
    ]
