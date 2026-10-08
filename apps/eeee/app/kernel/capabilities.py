"""Provider-neutral built-in adapters; the kernel owns their execution ledger."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from app.assistant.models import AssistantContext, AssistantRequest, CapabilityDescriptor, CapabilityPlan
from app.agent.protocol import AgentRequest, AgentRuntime
from app.agent.chatgpt_web_runtime import ChatGptWebRuntime
from app.config import Settings
from app.contracts import ExecutionEnvelope, ExecutionError, ExecutionStatus, SideEffectLevel
from app.coordinator.service import Coordinator
from app.integrations.contracts import ProjectOutcomeReportV1
from app.memory.preferences import extract_preference
from app.iseol.agents import AgentGraph
from app.iseol.executor import AgentGraphExecutor
from app.project_runtime.provisioner import ProjectProvisioner, is_todo_request
from app.planning.service import PlanningService
from app.runtime.store import StaleProjectRevision
from app.storage.sqlite import SQLiteStore
from app.workflow.planner import parse_request


@dataclass(frozen=True)
class CapabilityOutcome:
    output: dict[str, Any]
    status: ExecutionStatus = ExecutionStatus.COMPLETED
    error: ExecutionError | None = None


@dataclass(frozen=True)
class EnvelopeContext:
    envelope: ExecutionEnvelope
    assistant_context: AssistantContext
    run_child: Callable[..., ExecutionEnvelope]


class Capability(Protocol):
    descriptor: CapabilityDescriptor

    def plan(self, request: AssistantRequest, context: AssistantContext) -> CapabilityPlan: ...

    def execute(self, plan: CapabilityPlan, envelope_context: EnvelopeContext) -> CapabilityOutcome: ...


class LocalPlanningCapability:
    """Expose a local plan without claiming that a provider action occurred."""

    def __init__(self, descriptor: CapabilityDescriptor) -> None:
        self.descriptor = descriptor

    def plan(self, request: AssistantRequest, context: AssistantContext) -> CapabilityPlan:
        return CapabilityPlan(
            capability_id=self.descriptor.id,
            summary=request.raw_text,
            inputs={"text": request.raw_text},
            side_effect_level=self.descriptor.side_effect_level,
            requires_approval=self.descriptor.approval_level != "none",
        )

    def execute(self, plan: CapabilityPlan, envelope_context: EnvelopeContext) -> CapabilityOutcome:
        return CapabilityOutcome({
            "status": "selected", "capabilityStatus": "planned",
            "message": f"Selected EEEE capability: {self.descriptor.id}",
            "plan": plan.model_dump(mode="json"),
            "context": envelope_context.assistant_context.model_dump(mode="json"),
        })


class GeneralConversationCapability:
    """Keep EEEE useful when no specialized capability is required."""

    def __init__(self, descriptor: CapabilityDescriptor, *, runtime: AgentRuntime | None = None,
                 workspace_root: Path | None = None,
                 chatgpt_web_enabled: bool = False) -> None:
        self.descriptor = descriptor
        self.runtime = runtime
        self.workspace_root = workspace_root or Path.cwd()
        self.chatgpt_web_enabled = chatgpt_web_enabled

    def plan(self, request: AssistantRequest, context: AssistantContext) -> CapabilityPlan:
        return CapabilityPlan(
            capability_id=self.descriptor.id,
            summary=request.raw_text,
            inputs={
                "text": request.raw_text,
                "workspace": request.context.get("workspace"),
                "memoryIds": context.memory_ids,
                "qaBaselineIds": context.qa_baseline_ids,
                "userPreferences": context.user_preferences,
                "chatgptWebEnabled": self.chatgpt_web_enabled,
            },
            side_effect_level=self.descriptor.side_effect_level,
            requires_approval=False,
        )

    def execute(self, plan: CapabilityPlan, envelope_context: EnvelopeContext) -> CapabilityOutcome:
        if self.runtime is not None:
            workspace_value = plan.inputs.get("workspace")
            workspace = Path(workspace_value) if isinstance(workspace_value, str) and workspace_value else (
                self.workspace_root / "assistant"
            )
            result = self.runtime.run(AgentRequest(
                prompt=(
                    f"사용자 요청: {plan.inputs['text']}\n"
                    f"사용자 기억: {json.dumps({
                        'memoryIds': plan.inputs.get('memoryIds', []),
                        'qaBaselineIds': plan.inputs.get('qaBaselineIds', []),
                        'userPreferences': plan.inputs.get('userPreferences', {}),
                    }, ensure_ascii=False, sort_keys=True)}"
                ),
                workspace=workspace,
                allowed_actions=["read"], run_id=envelope_context.envelope.execution_id,
            ))
            if result.status == "completed":
                return CapabilityOutcome({
                    "status": "completed", "capabilityStatus": "completed",
                    "message": result.summary,
                    "runtimeStatus": result.status, "events": result.events,
                })
            status = ExecutionStatus.FAILED if result.status == "failed" else ExecutionStatus.BLOCKED
            return CapabilityOutcome({
                "status": "blocked", "capabilityStatus": result.status,
                "message": result.error or "실제 AI 응답을 사용할 수 없어.",
                "runtimeStatus": result.status,
            }, status, ExecutionError(code="assistant_runtime_unavailable", message=result.error or result.status))
        if plan.inputs.get("chatgptWebEnabled"):
            return CapabilityOutcome({
                "status": "blocked",
                "capabilityStatus": "blocked",
                "message": "ChatGPT Web 연결이 설정되지 않았어. 브라우저 연결을 먼저 완료해줘.",
                "runtimeStatus": "unavailable",
            }, ExecutionStatus.BLOCKED, ExecutionError(
                code="chatgpt_web_bridge_unavailable",
                message="ChatGPT Web bridge is not configured",
            ))
        return CapabilityOutcome({
            "status": "completed",
            "capabilityStatus": "completed",
            "message": "EEEE가 요청을 이해했어. 필요한 작업이 있으면 말해줘.",
            "context": envelope_context.assistant_context.model_dump(mode="json"),
        })


class UserPreferenceCapability:
    """Persist only explicitly phrased user preferences."""

    def __init__(self, descriptor: CapabilityDescriptor, coordinator: Coordinator) -> None:
        self.descriptor = descriptor
        self.coordinator = coordinator

    def plan(self, request: AssistantRequest, context: AssistantContext) -> CapabilityPlan:
        preference = extract_preference(request.raw_text)
        if preference is None:
            raise ValueError("명시적으로 기억할 선호를 말해줘.")
        return CapabilityPlan(
            capability_id=self.descriptor.id,
            summary=f"Remember {preference.key}",
            inputs={"key": preference.key, "value": preference.value},
            side_effect_level=self.descriptor.side_effect_level,
            requires_approval=False,
        )

    def execute(self, plan: CapabilityPlan, envelope_context: EnvelopeContext) -> CapabilityOutcome:
        record = self.coordinator.remember_user_preference(
            str(plan.inputs["key"]), str(plan.inputs["value"])
        )
        return CapabilityOutcome({
            "status": "completed",
            "message": "기억해둘게.",
            "memoryId": record.id,
            "preferenceKey": plan.inputs["key"],
            "preferenceValue": plan.inputs["value"],
        })


class ProjectExecutionCapability:
    """Allocate one local project, then delegate its request and profile to ISEOL."""

    def __init__(
        self, descriptor: CapabilityDescriptor, *, coordinator: Coordinator,
        store: SQLiteStore, settings: Settings, provisioner: ProjectProvisioner,
        document_service: Any | None = None, planning_service: PlanningService | None = None,
        agent_runtime: AgentRuntime | None = None,
    ) -> None:
        self.descriptor = descriptor
        self.coordinator = coordinator
        self.store = store
        self.settings = settings
        self.provisioner = provisioner
        self.document_service = document_service
        self.planning_service = planning_service or PlanningService(store)
        self.agent_runtime = agent_runtime

    def plan(self, request: AssistantRequest, context: AssistantContext) -> CapabilityPlan:
        project_id = f"project-{uuid4().hex}"
        root = self.settings.workspace_root.resolve()
        requested = request.context.get("workspace")
        workspace = Path(requested).resolve() if requested else root / "assistant" / project_id
        try:
            workspace.relative_to(root)
        except ValueError as exc:
            raise ValueError("Workspace must be inside the configured workspace root") from exc
        return CapabilityPlan(
            capability_id=self.descriptor.id, summary=request.raw_text,
            inputs={"text": request.raw_text, "projectId": project_id, "workspace": str(workspace)},
            side_effect_level=self.descriptor.side_effect_level,
            requires_approval=self.descriptor.approval_level != "none",
        )

    def execute(self, plan: CapabilityPlan, envelope_context: EnvelopeContext) -> CapabilityOutcome:
        text = plan.inputs["text"]
        brief = parse_request(text)
        project = self.coordinator.create_project(
            plan.inputs["projectId"], brief.goal[:80], plan.inputs["workspace"],
        )
        try:
            state = self.coordinator.create_request(project.id, text)
            if state.request_id is None:
                raise RuntimeError("Project request did not produce a request ID")
            self.store.save_request_context(state.request_id, project.id, project.workspace)
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            return CapabilityOutcome(
                {"status": "blocked", "message": message, "projectId": project.id,
                 "projectRevision": project.revision},
                ExecutionStatus.FAILED, ExecutionError(code="capability_failed", message=message),
            )

        def provision(_child: ExecutionEnvelope) -> CapabilityOutcome:
            project_brief = self.coordinator.build_project_brief(project.id, state.request_id)
            planning_handoff = self.planning_service.quick_plan(
                project, brief,
                memory_ids=list(dict.fromkeys([
                    *project_brief.retrieved_memory_ids, *envelope_context.assistant_context.memory_ids,
                ])),
                qa_baseline_ids=list(dict.fromkeys([
                    *project_brief.qa_baseline_ids, *envelope_context.assistant_context.qa_baseline_ids,
                ])),
            )
            provisioned = self.provisioner.provision(
                project, brief,
                memory_ids=list(dict.fromkeys([
                    *project_brief.retrieved_memory_ids, *envelope_context.assistant_context.memory_ids,
                ])),
                qa_baseline_ids=list(dict.fromkeys([
                    *project_brief.qa_baseline_ids, *envelope_context.assistant_context.qa_baseline_ids,
                ])),
                memory_context=[
                    *list(project_brief.preferences.get("verifiedMemories", [])),
                    *[
                        {"kind": "user_preference", "key": key, "content": value}
                        for key, value in project_brief.preferences.get("userPreferences", {}).items()
                    ],
                ],
                request_id=state.request_id,
                planning_handoff=planning_handoff,
            )
            agent_graph = _read_agent_graph(provisioned.execution_plan_path)
            agent_execution_report = None
            if self.agent_runtime is not None and agent_graph.get("agents"):
                agent_execution_report = AgentGraphExecutor(
                    runtime=self.agent_runtime,
                    trust_pipeline=self.coordinator.trust_pipeline,
                    workspace=Path(project.workspace),
                ).execute(AgentGraph.model_validate(agent_graph), _child)
                if agent_execution_report.status != "completed":
                    return CapabilityOutcome(
                        {
                            "status": "blocked",
                            "message": "ISEOL specialist agent graph did not pass all handoff gates",
                            "projectId": project.id,
                            "projectRevision": project.revision,
                            "agentGraph": agent_graph,
                            "agentExecutionReport": agent_execution_report.model_dump(mode="json", by_alias=True),
                        },
                        ExecutionStatus.BLOCKED,
                        ExecutionError(code="agent_graph_blocked", message="Agent graph handoff was blocked"),
                    )
            todo_run = None
            web_run = None
            memory_records = []
            # Keep the original user utterance in the product-type decision.
            # The parsed goal is intentionally normalized and can vary by
            # locale/parser implementation; a direct request such as
            # "Todo 앱 만들어줘" must never skip the verified Todo runner.
            if brief.runtime_profile == "web_app":
                prepared = self.provisioner.web_runner.prepare(
                    project_id=project.id,
                    project_revision=project.revision,
                    workspace=project.workspace,
                )
                trust = (
                    self.coordinator.trust_pipeline.release_gate(_child, prepared.qa_report)
                    if self.coordinator.trust_pipeline is not None
                    else None
                )
                claim_latch = {
                    "decision": trust.decision if trust is not None else "BLOCKED",
                    "receiptId": trust.claim_latch_receipt_id if trust is not None else None,
                    "claimLatchReportId": trust.claim_latch_report_id if trust is not None else None,
                }
                web_run = self.provisioner.web_runner.finalize(
                    project_id=project.id,
                    project_revision=project.revision,
                    workspace=project.workspace,
                    prepared=prepared,
                    claim_latch=claim_latch,
                )
            elif is_todo_request(text, [brief.goal, brief.target_type, *brief.acceptance_criteria]):
                prepared = self.provisioner.todo_runner.prepare(
                    project_id=project.id,
                    project_revision=project.revision,
                    workspace=project.workspace,
                )
                trust = (
                    self.coordinator.trust_pipeline.release_gate(_child, prepared.qa_report)
                    if self.coordinator.trust_pipeline is not None
                    else None
                )
                claim_latch = {
                    "decision": trust.decision if trust is not None else "BLOCKED",
                    "receiptId": trust.claim_latch_receipt_id if trust is not None else None,
                    "claimLatchReportId": trust.claim_latch_report_id if trust is not None else None,
                }
                todo_run = self.provisioner.todo_runner.finalize(
                    project_id=project.id,
                    project_revision=project.revision,
                    workspace=project.workspace,
                    prepared=prepared,
                    claim_latch=claim_latch,
                )
                if todo_run.status == "PASS" and trust is not None and trust.decision == "PASS":
                    outcome = ProjectOutcomeReportV1.model_validate({
                        "schemaVersion": 1,
                        "projectId": project.id,
                        "requestId": state.request_id,
                        "projectRevision": project.revision,
                        "status": "completed",
                        "artifacts": prepared.artifacts,
                        "agentTeams": [
                            {"id": agent["id"], "agent": agent["id"], "role": agent["role"]}
                            for agent in agent_graph.get("agents", [])
                        ],
                        "handoffs": [],
                        "deterministicVerification": {
                            "status": "PASS",
                            "runner": "EEEE.TodoProjectRunner",
                            "evidenceIds": prepared.qa_report["evidenceIds"],
                        },
                        "qaReport": prepared.qa_report,
                        "claimLatchReports": [{
                            "id": trust.claim_latch_report_id,
                            "claimLatchReportId": trust.claim_latch_report_id,
                            "projectId": project.id,
                            "projectRevision": project.revision,
                            "decision": "PASS",
                        }],
                        "receipts": [{"receiptId": trust.claim_latch_receipt_id}],
                        "risks": [],
                        "memoryCandidates": [{
                            "candidateId": f"memory-{project.id}-todo-pattern",
                            "kind": "success_pattern",
                            "content": "Todo 프로젝트는 FSD 계층과 독립 QA를 함께 생성하고, ClaimLatch PASS 이후에만 릴리스한다.",
                            "scope": {"projectType": "todo", "qualityGate": "claimlatch-v0.2.0"},
                            "confidence": 0.9,
                        }],
                        "createdAt": datetime.now(timezone.utc),
                    })
                    memory_records = self.coordinator.record_verified_project_outcome(outcome)
            document_execution_id = None
            if self.document_service is not None:
                def sync_document(_document: ExecutionEnvelope) -> CapabilityOutcome:
                    result = self.document_service.sync(provisioned.profile)
                    status = (ExecutionStatus.COMPLETED if result.status in {"synced", "unchanged"}
                              else ExecutionStatus.BLOCKED)
                    return CapabilityOutcome(result.model_dump(mode="json", by_alias=True), status)

                document = envelope_context.run_child(
                    parent=_child, project_id=project.id, revision=project.revision,
                    request_id=state.request_id, tool_id="project.documents.sync",
                    inputs={"provider": "notion"}, side_effect_level=SideEffectLevel.EXTERNAL,
                    operation=sync_document, owns_trust_boundary=True,
                )
                document_execution_id = document.execution_id
                if document.status == ExecutionStatus.FAILED:
                    return CapabilityOutcome(
                        {"status": "blocked", "message": document.error.message,
                         "documentExecutionId": document.execution_id},
                        ExecutionStatus.FAILED, document.error,
                    )
            profile = self.store.get_project_profile(project.id)
            missing = sorted(binding.connector_id for binding in profile.connectors
                             if binding.state in {"awaiting_configuration", "planned"})
            return CapabilityOutcome({
                "status": profile.provisioning_status,
                "message": "Project Runtime이 생성되었고 외부 연결 상태를 확인해야 해.",
                "projectId": project.id, "projectProfile": profile.model_dump(mode="json", by_alias=True),
                "missingConnectors": missing, "documentExecutionId": document_execution_id,
                "executionPlanPath": provisioned.execution_plan_path,
                "agentGraph": agent_graph,
                "agentExecutionReport": agent_execution_report.model_dump(mode="json", by_alias=True)
                if agent_execution_report is not None else None,
                "planningSessionId": planning_handoff.planning_session_id,
                "planningHandoffId": planning_handoff.handoff_id,
                "qaReportPath": (web_run.qa_report_path if web_run is not None else todo_run.qa_report_path if todo_run is not None else None),
                "releaseManifestPath": (web_run.release_manifest_path if web_run is not None else todo_run.release_manifest_path if todo_run is not None else None),
                "gitBranch": (web_run.git_branch if web_run is not None else todo_run.git_branch if todo_run is not None else None),
                "gitCommit": (web_run.git_commit if web_run is not None else todo_run.git_commit if todo_run is not None else None),
                "qualityStatus": (web_run.status if web_run is not None else todo_run.status if todo_run is not None else None),
                "qualityReason": (web_run.reason if web_run is not None else todo_run.reason if todo_run is not None else None),
                "memoryCandidateIds": [record.id for record in memory_records],
            }, ExecutionStatus.COMPLETED)

        try:
            child = envelope_context.run_child(
                parent=envelope_context.envelope, project_id=project.id, revision=project.revision,
                request_id=state.request_id, tool_id="iseol", inputs={"text": text, "workspace": project.workspace},
                side_effect_level=SideEffectLevel.LOCAL, operation=provision,
            )
        except StaleProjectRevision as exc:
            message = str(exc).strip() or "stale project revision"
            return CapabilityOutcome(
                {
                    "status": "blocked",
                    "message": message,
                    "projectId": project.id,
                    "projectRevision": project.revision,
                    "coordinatorRequestId": state.request_id,
                },
                ExecutionStatus.FAILED,
                ExecutionError(code="stale_project_revision", message=message),
            )
        output = dict(child.model_dump(mode="json")["output"] or {})
        output.update(projectId=project.id, projectRevision=project.revision, childExecutionId=child.execution_id,
                      coordinatorRequestId=state.request_id)
        status = (ExecutionStatus.FAILED if child.error is not None and child.error.code == "stale_project_revision"
                  else child.status)
        return CapabilityOutcome(output, status, child.error)


def _read_agent_graph(path: str | None) -> dict[str, Any]:
    if not path:
        return {"schemaVersion": "iseol-agent-graph.v1", "agents": []}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": "iseol-agent-graph.v1", "agents": []}
    graph = payload.get("agentGraph") if isinstance(payload, dict) else None
    return graph if isinstance(graph, dict) and isinstance(graph.get("agents"), list) else {
        "schemaVersion": "iseol-agent-graph.v1", "agents": []
    }
