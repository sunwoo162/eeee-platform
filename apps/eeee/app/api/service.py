"""Application service for the request/research/approval/run API."""

from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from threading import Event, Thread
from typing import Callable
from uuid import uuid4

from app.agent.protocol import AgentRequest, AgentResult, AgentRuntime
from app.assistant.models import AssistantRequest
from app.assistant.registry import build_default_registry
from app.assistant.router import CapabilityRouter
from app.config import Settings
from app.coordinator.service import Coordinator
from app.domain.errors import ApprovalError
from app.domain.models import CandidateScore, Decision, RequestBrief, RequestSnapshot, Run
from app.storage.sqlite import SQLiteStore
from app.trust.gate import TrustGate
from app.workflow.planner import WorkPlan, build_work_plan
from app.workspace.artifacts import WorkspaceArtifactWriter
from app.project_runtime.provisioner import ProjectProvisioner
from app.contracts import ExecutionEnvelope, ExecutionStatus
from app.trust.pipeline import TrustPipeline
from app.conversations.models import MessageStatus
from app.conversations.store import ConversationStore


class ApiFlowService:
    """Coordinate the HTTP flow while keeping runtime calls behind an interface."""

    LEASE_SECONDS = 60
    HEARTBEAT_INTERVAL_SECONDS = 10.0

    def __init__(
        self,
        coordinator: Coordinator,
        store: SQLiteStore,
        settings: Settings,
        runtime: AgentRuntime,
        artifact_writer: WorkspaceArtifactWriter | None = None,
        clock: Callable[[], datetime] | None = None,
        lease_seconds: int = LEASE_SECONDS,
        heartbeat_interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
        capability_router: CapabilityRouter | None = None,
        project_provisioner: ProjectProvisioner | None = None,
        trust_gate: TrustGate | None = None,
        trust_pipeline: TrustPipeline | None = None,
        event_publisher: Callable[[str, dict[str, object]], object] | None = None,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.store = store
        self.settings = settings
        self.runtime = runtime
        self.artifacts = artifact_writer or WorkspaceArtifactWriter()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.lease_seconds = lease_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.capability_router = capability_router or CapabilityRouter(build_default_registry())
        self.project_provisioner = project_provisioner or ProjectProvisioner(store)
        self.trust_gate = trust_gate or TrustGate(None, mode="advisory")
        self.trust_pipeline = trust_pipeline or TrustPipeline(
            self.trust_gate, audit_store=store.claimlatch_audits
        )
        self.event_publisher = event_publisher
        self.conversation_store = conversation_store

    def create_request(
        self,
        text: str,
        workspace: str | None,
        *,
        conversation_id: str = "desktop-default",
        user_id: str = "local-user",
    ) -> tuple[str, RequestBrief, str]:
        # `/api/requests` is the legacy project workbench endpoint. The new
        # `/api/assistant/route` endpoint is the canonical intent-aware entrypoint;
        # this compatibility path keeps accepting arbitrary project descriptions.
        self.capability_router.select(AssistantRequest(raw_text=text))
        project_id = f"api-{uuid4().hex}"
        workspace_path = self._resolve_workspace(workspace, project_id)
        workspace_path.mkdir(parents=True, exist_ok=True)
        self.coordinator.create_project(
            project_id, text[:80], str(workspace_path), user_id=user_id
        )
        state = self.coordinator.create_request(project_id, text, user_id=user_id)
        if state.request_id is None:
            raise RuntimeError("Created request did not produce a request ID")
        request_id = state.request_id
        self.store.save_request_context(
            request_id, project_id, str(workspace_path), conversation_id
        )
        project_brief = self.coordinator.build_project_brief(
            project_id, request_id, user_id=user_id
        )
        self.project_provisioner.provision(
            self.store.get_project(project_id, user_id=user_id),
            self.store.get_request(request_id),
            memory_ids=project_brief.retrieved_memory_ids,
            qa_baseline_ids=project_brief.qa_baseline_ids,
            user_id=user_id,
        )
        run = self.store.create_run(request_id, str(workspace_path))
        self._record_legacy_request(
            request_id,
            conversation_id,
            text,
            "프로젝트 요청을 접수했어. 조사와 승인 후 실행할 수 있어.",
            MessageStatus.PENDING,
            user_id=user_id,
        )
        return request_id, self.store.get_request(request_id), run.id

    def research(
        self, request_id: str, *, user_id: str | None = None
    ) -> tuple[list[CandidateScore], WorkPlan]:
        project_id, _workspace, _project = self._project_for_request(
            request_id, user_id=user_id
        )
        state = self.coordinator.get_state(project_id, user_id=user_id)
        if state.state.value == "researching":
            state = self.coordinator.advance_task(
                project_id, state.task_id or "", user_id=user_id
            )
        if state.state.value == "failed":
            raise RuntimeError(state.message)
        candidates = self.store.get_candidates(request_id)
        return candidates, build_work_plan(self.store.get_request(request_id), candidates)

    def approve(
        self, request_id: str, selected: list[str], *, user_id: str | None = None
    ) -> tuple[Decision, str, list[dict[str, object]]]:
        project_id, _workspace, _project = self._project_for_request(
            request_id, user_id=user_id
        )
        self.coordinator.approve_selection(
            project_id, request_id, selected, user_id=user_id
        )
        decision = self.store.get_decision(request_id)
        if decision is None or not decision.approved:
            raise ApprovalError("Approval was not persisted")
        run = self.store.get_run_for_request(request_id)
        return decision, run.id, self.store.get_decision_events(request_id)

    def execute(self, run_id: str, *, user_id: str | None = None) -> Run:
        run = self.store.get_run(run_id)
        project_id, _workspace, project = self._project_for_request(
            run.request_id, user_id=user_id
        )
        decision = self.store.get_decision(run.request_id)
        if decision is None or not decision.approved:
            raise ApprovalError("Run execution requires an approved decision")

        owner_token = uuid4().hex
        claim = self.store.claim_run_execution(
            run_id, owner_token, self._clock, self.lease_seconds
        )
        if not claim.acquired:
            return claim.run
        run = claim.run
        self._publish(
            "run.execution.started",
            {"runId": run.id, "requestId": run.request_id},
            user_id=user_id,
        )
        stop_heartbeat = Event()

        def heartbeat() -> None:
            while not stop_heartbeat.wait(self.heartbeat_interval_seconds):
                try:
                    if not self.store.renew_run_execution(
                        run_id, owner_token, claim.generation, self._clock,
                        self.lease_seconds,
                    ):
                        break
                except Exception:
                    break

        heartbeat_thread = Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()

        try:
            request = AgentRequest(
                prompt=self.store.get_request(run.request_id).raw_text,
                workspace=Path(run.workspace),
                allowed_actions=["read", "workspace_write", "command"],
                run_id=run.id,
            )
            try:
                result = self.runtime.run(request)
            except Exception:
                result = AgentResult(
                    status="failed",
                    summary="Agent runtime raised an unexpected error",
                    events=[],
                    changed_files=[],
                    test_commands=[],
                    error="Agent runtime raised an unexpected error",
                )
            if result.status not in {"completed", "failed", "unavailable"}:
                result = AgentResult(
                    status="failed",
                    summary=result.summary,
                    events=result.events,
                    changed_files=result.changed_files,
                    test_commands=result.test_commands,
                    error=f"Agent runtime returned non-terminal status: {result.status}",
                )
            events = list(result.events)
            trust_envelope = ExecutionEnvelope(
                execution_id=f"{run.id}:agent-result",
                request_id=run.request_id,
                project_id=project_id,
                project_revision=project.revision,
                capability_id="agent-result",
                tool_id="api-runtime",
                actor="EEEE",
                status=ExecutionStatus.RUNNING,
                input={"summary": result.summary},
                evidence_ids=tuple(
                    str(event.get("evidenceId"))
                    for event in result.events
                    if isinstance(event, dict) and isinstance(event.get("evidenceId"), str)
                ),
            )
            trust = self.trust_pipeline.verify_claim(trust_envelope)
            events.append(
                {
                    "type": "claimlatch",
                    "decision": trust.decision,
                    "reason": trust.reason,
                    "profileVersion": self.trust_gate.profile_version,
                    "engineVersion": self.trust_gate.engine_version,
                }
            )
            if trust.decision == "BLOCKED":
                result = AgentResult(
                    status="failed",
                    summary=result.summary,
                    events=result.events,
                    changed_files=result.changed_files,
                    test_commands=result.test_commands,
                    error=f"ClaimLatch blocked agent result release: {trust.reason}",
                )
            if result.test_commands and not any(
                str(event.get("type", "")).lower() == "verification" for event in result.events
            ):
                events.append(
                    {"type": "verification", "status": "reported", "commands": result.test_commands},
                )
            if not self.store.renew_run_execution(
                run_id, owner_token, claim.generation, self._clock,
                self.lease_seconds,
            ):
                return self.store.get_run(run_id)
            decision = self.store.get_decision(run.request_id)
            if decision is None:
                raise ApprovalError("Run execution requires an approved decision")
            bundle_paths = self.artifacts.write_run_bundle(
                run.workspace,
                run.id,
                brief=self.store.get_request(run.request_id),
                decision=decision,
                candidates=self.store.get_candidates(run.request_id),
                status=result.status,
                summary=result.summary,
                changed_files=result.changed_files,
                test_commands=result.test_commands,
                error=result.error,
            )
            artifact = {
                "type": "agent_result",
                "summary": result.summary,
                "changed_files": result.changed_files,
                "test_commands": result.test_commands,
            }
            artifacts = [artifact] + [
                {"type": "run_bundle", "path": str(path)} for path in bundle_paths
            ]
            completed = self.store.complete_run_execution(
                run.id, owner_token, claim.generation, result.status,
                events, artifacts, result.error, self._clock,
            )
            self._publish(
                "run.execution.completed",
                {"runId": run.id, "requestId": run.request_id, "status": result.status},
                user_id=user_id,
            )
            self._record_legacy_request(
                run.request_id,
                self.store.get_request_conversation_id(run.request_id),
                self.store.get_request(run.request_id).raw_text,
                result.summary,
                MessageStatus.COMPLETED
                if result.status == "completed"
                else MessageStatus.FAILED,
                error_code=result.error,
                user_id=user_id or "local-user",
            )
            return completed if completed is not None else self.store.get_run(run_id)
        except Exception:
            try:
                self.store.complete_run_execution(
                    run.id, owner_token, claim.generation, "failed", [], [],
                    "Run execution failed while persisting its result", self._clock,
                )
            except Exception:
                pass
            try:
                self._record_legacy_request(
                    run.request_id,
                    self.store.get_request_conversation_id(run.request_id),
                    self.store.get_request(run.request_id).raw_text,
                    "프로젝트 실행 결과를 저장하지 못했어.",
                    MessageStatus.FAILED,
                    error_code="legacy_run_persistence_failed",
                    user_id=user_id or "local-user",
                )
            except Exception:
                pass
            raise
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join()

    def _publish(
        self,
        kind: str,
        payload: dict[str, object],
        *,
        user_id: str | None = None,
    ) -> None:
        if self.event_publisher is not None:
            scoped_payload = dict(payload)
            if user_id:
                scoped_payload.setdefault("userId", user_id)
            self.event_publisher(kind, scoped_payload)

    def get_run(self, run_id: str, *, user_id: str | None = None) -> Run:
        run = self.store.get_run(run_id)
        self._project_for_request(run.request_id, user_id=user_id)
        return run

    def list_runs(
        self,
        request_id: str | None = None,
        *,
        status: str | None = None,
        search: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        user_id: str | None = None,
    ) -> list[Run]:
        if user_id is not None:
            runs, _total = self.list_runs_with_count(
                request_id,
                status=status,
                search=search,
                created_after=created_after,
                created_before=created_before,
                sort=sort,
                limit=limit,
                offset=offset,
                user_id=user_id,
            )
            return runs
        return self.store.list_runs(
            request_id,
            status=status,
            search=search,
            created_after=created_after,
            created_before=created_before,
            sort=sort,
            limit=limit,
            offset=offset,
        )

    def count_runs(
        self,
        request_id: str | None = None,
        *,
        status: str | None = None,
        search: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        user_id: str | None = None,
    ) -> int:
        if user_id is not None:
            _runs, total = self.list_runs_with_count(
                request_id,
                status=status,
                search=search,
                created_after=created_after,
                created_before=created_before,
                user_id=user_id,
            )
            return total
        return self.store.count_runs(
            request_id,
            status=status,
            search=search,
            created_after=created_after,
            created_before=created_before,
        )

    def list_runs_with_count(
        self,
        request_id: str | None = None,
        *,
        status: str | None = None,
        search: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        user_id: str | None = None,
    ) -> tuple[list[Run], int]:
        if user_id is not None:
            all_runs = self.store.list_runs(
                request_id,
                status=status,
                search=search,
                created_after=created_after,
                created_before=created_before,
                sort=sort,
            )
            owned_runs = []
            for run in all_runs:
                try:
                    self._project_for_request(run.request_id, user_id=user_id)
                except KeyError:
                    continue
                owned_runs.append(run)
            total = len(owned_runs)
            if limit is None:
                return owned_runs[offset:], total
            return owned_runs[offset : offset + limit], total
        return self.store.list_runs_with_count(
            request_id,
            status=status,
            search=search,
            created_after=created_after,
            created_before=created_before,
            sort=sort,
            limit=limit,
            offset=offset,
        )

    def get_request_snapshot(
        self, request_id: str, *, user_id: str | None = None
    ) -> RequestSnapshot:
        project_id, workspace, _project = self._project_for_request(
            request_id, user_id=user_id
        )
        brief = self.store.get_request(request_id)
        return RequestSnapshot(
            request_id=request_id,
            project_id=project_id,
            brief=brief,
            workspace=workspace,
            candidates=self.store.get_candidates(request_id),
            decision=self.store.get_decision(request_id),
            decision_events=self.store.get_decision_events(request_id),
            runs=self.list_runs(request_id, user_id=user_id),
        )

    def retry(self, run_id: str, *, user_id: str | None = None) -> Run:
        run = self.store.get_run(run_id)
        self._project_for_request(run.request_id, user_id=user_id)
        decision = self.store.get_decision(run.request_id)
        if decision is None or not decision.approved:
            raise ApprovalError("Run retry requires an approved decision")
        retried = self.store.reset_run_for_retry(run.id)
        self._record_legacy_request(
            run.request_id,
            self.store.get_request_conversation_id(run.request_id),
            self.store.get_request(run.request_id).raw_text,
            "프로젝트 실행을 다시 준비하고 있어.",
            MessageStatus.PENDING,
            error_code=None,
            user_id=user_id or "local-user",
        )
        return retried

    def _project_for_request(
        self, request_id: str, *, user_id: str | None = None
    ) -> tuple[str, str, object]:
        project_id, workspace = self.store.get_request_context(request_id)
        project = self.store.get_project(project_id, user_id=user_id)
        return project_id, workspace, project

    def _record_legacy_request(
        self,
        request_id: str,
        conversation_id: str,
        user_text: str,
        assistant_text: str,
        status: MessageStatus,
        *,
        error_code: str | None = None,
        user_id: str = "local-user",
    ) -> None:
        if self.conversation_store is None:
            return
        self.conversation_store.record_route_turn(
            conversation_id,
            user_content=user_text,
            assistant_content=assistant_text,
            request_id=request_id,
            assistant_status=status,
            error_code=error_code,
            user_id=user_id,
        )
        self.conversation_store.record_route_lifecycle(
            conversation_id,
            request_id,
            "completed" if status is MessageStatus.COMPLETED else "failed"
            if status is MessageStatus.FAILED
            else "accepted",
            error_code=error_code,
            user_id=user_id,
        )

    def _resolve_workspace(self, requested: str | None, project_id: str) -> Path:
        root = self.settings.workspace_root.resolve()
        candidate = Path(requested).resolve() if requested else root / "api" / project_id
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("Workspace must be inside the configured workspace root") from exc
        return candidate
