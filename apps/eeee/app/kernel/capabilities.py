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
from app.assistant.secretary import PersonalSecretary, SecretaryContext
from app.assistant.reminders import ReminderStore, parse_reminder
from app.knowledge.service import KnowledgeService
from app.knowledge.store import KnowledgeStore
from app.agent.protocol import AgentRequest, AgentRuntime
from app.agent.chatgpt_web_runtime import ChatGptWebRuntime
from app.config import Settings
from app.contracts import ExecutionEnvelope, ExecutionError, ExecutionStatus, SideEffectLevel
from app.coordinator.service import Coordinator
from app.integrations.contracts import ProjectOutcomeReportV1
from app.memory.preferences import extract_preference
from app.iseol.agents import AgentGraph
from app.iseol.contracts import ProjectExecutionPlan, ProjectIntent
from app.iseol.executor import AgentGraphExecutor
from app.iseol.intake import NaturalLanguageIntake
from app.iseol.orchestrator import IseolOrchestrator
from app.iseol.review import ProjectQualityEvaluator
from app.project_runtime.provisioner import ProjectProvisioner, is_todo_request
from app.planning.service import PlanningService
from app.runtime.store import StaleProjectRevision
from app.storage.sqlite import SQLiteStore


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
        if self.descriptor.id == "presence":
            return CapabilityOutcome(
                {
                    "status": "unsupported",
                    "capabilityStatus": "unsupported",
                    "reasonCode": "presence_provider_unavailable",
                    "message": "현재 바탕화면·모바일 표시 기능이 연결되어 있지 않아 실행할 수 없어.",
                },
                ExecutionStatus.BLOCKED,
                ExecutionError(
                    code="presence_provider_unavailable",
                    message="Presence provider is not configured",
                ),
            )
        return CapabilityOutcome({
            "status": "selected", "capabilityStatus": "planned",
            "message": f"Selected EEEE capability: {self.descriptor.id}",
            "plan": plan.model_dump(mode="json"),
            "context": envelope_context.assistant_context.model_dump(mode="json"),
        })


class LocalSecretaryCapability:
    """Execute the local-first secretary lane without requiring a plugin."""

    def __init__(self, descriptor, *, store: SQLiteStore) -> None:
        self.descriptor = descriptor
        self.reminders = ReminderStore(store.path)

    def plan(self, request: AssistantRequest, context: AssistantContext) -> CapabilityPlan:
        return CapabilityPlan(
            capability_id=self.descriptor.id,
            summary=request.raw_text,
            inputs={"text": request.raw_text, "conversationId": context.conversation_id},
            side_effect_level=self.descriptor.side_effect_level,
            requires_approval=False,
        )

    def execute(self, plan: CapabilityPlan, envelope_context: EnvelopeContext) -> CapabilityOutcome:
        text = str(plan.inputs.get("text", "")).strip()
        conversation_id = str(plan.inputs.get("conversationId", "desktop-default"))
        if any(marker in text for marker in ("보여줘", "보여", "확인", "목록", "뭐가", "뭐 있어")):
            reminders = [item.as_dict() for item in self.reminders.list(conversation_id)]
            message = (
                "등록된 일정이 없어."
                if not reminders
                else "\n".join(f"- {item['title']} ({item['dueAt']})" for item in reminders)
            )
            return CapabilityOutcome({
                "status": "completed", "capabilityStatus": "completed",
                "message": message, "reminders": reminders,
            })
        draft = parse_reminder(text)
        if draft is None:
            return CapabilityOutcome(
                {
                    "status": "blocked", "capabilityStatus": "blocked",
                    "message": "언제 할 일정인지 시간까지 말해줘. 예: 내일 오후 3시에 팀 회의 알려줘",
                },
                ExecutionStatus.BLOCKED,
                ExecutionError(code="reminder_time_required", message="Reminder time is required"),
            )
        reminder = self.reminders.create(
            conversation_id, draft, request_id=envelope_context.envelope.request_id,
        )
        return CapabilityOutcome({
            "status": "completed", "capabilityStatus": "completed",
            "message": f"{reminder.title} 일정을 {reminder.due_at.strftime('%m월 %d일 %H:%M')}로 저장했어.",
            "reminder": reminder.as_dict(),
        })


class KnowledgeDocumentsCapability:
    """Run bounded local document commands without promoting them to memory."""

    def __init__(self, descriptor, *, store: SQLiteStore) -> None:
        self.descriptor = descriptor
        self.service = KnowledgeService(KnowledgeStore(store.path))

    def plan(self, request: AssistantRequest, context: AssistantContext) -> CapabilityPlan:
        return CapabilityPlan(
            capability_id=self.descriptor.id,
            summary=request.raw_text,
            inputs={
                "text": request.raw_text,
                "scope": context.conversation_id,
            },
            side_effect_level=self.descriptor.side_effect_level,
            requires_approval=False,
        )

    def execute(self, plan: CapabilityPlan, envelope_context: EnvelopeContext) -> CapabilityOutcome:
        result = self.service.handle(
            str(plan.inputs.get("text", "")),
            scope=str(plan.inputs.get("scope", "desktop-default")),
        )
        output = {
            "status": result.status,
            "capabilityStatus": result.status,
            "message": result.message,
            "document": result.document,
            "documents": result.documents,
            "summary": result.summary,
            "sources": result.sources,
        }
        if result.error_code is not None:
            output["errorCode"] = result.error_code
            return CapabilityOutcome(
                output,
                ExecutionStatus.BLOCKED,
                ExecutionError(code=result.error_code, message=result.message),
            )
        return CapabilityOutcome(output)


class GeneralConversationCapability:
    """Keep EEEE useful when no specialized capability is required."""

    def __init__(self, descriptor: CapabilityDescriptor, *, runtime: AgentRuntime | None = None,
                 workspace_root: Path | None = None,
                 chatgpt_web_enabled: bool = False) -> None:
        self.descriptor = descriptor
        if runtime is None:
            # A fresh installation must still be conversational immediately.
            # This bounded offline lane handles common turns without pretending
            # to be a full LLM; complex questions remain eligible for Web/local
            # provider escalation when one is configured.
            from app.agent.hybrid_runtime import FastLocalConversationRuntime

            runtime = FastLocalConversationRuntime()
        self.runtime = runtime
        self.workspace_root = workspace_root or Path.cwd()
        self.chatgpt_web_enabled = chatgpt_web_enabled
        self.secretary = PersonalSecretary()

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
                "memoryContext": context.memory_context,
                "conversationId": context.conversation_id,
                "conversationHistory": context.conversation_turns,
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
            # General conversation uses the same bounded local runtime as the
            # project lane, but it does not have a provisioner step that would
            # create the default workspace first. Create that private runtime
            # directory at the capability boundary so a real local model can
            # answer ordinary chat without being rejected by workspace safety.
            workspace.mkdir(parents=True, exist_ok=True)
            result = self.runtime.run(AgentRequest(
                prompt=self.secretary.build_prompt(
                    str(plan.inputs['text']),
                    SecretaryContext(
                        conversation_id=str(plan.inputs.get('conversationId', 'desktop-default')),
                        recent_turns=list(plan.inputs.get('conversationHistory', [])),
                        preferences=dict(plan.inputs.get('userPreferences', {})),
                        memory_context=str(plan.inputs.get('memoryContext', '{}')),
                    ),
                ),
                workspace=workspace,
                allowed_actions=["read"], run_id=envelope_context.envelope.execution_id,
            ))
            if result.status == "completed" and not result.summary.strip():
                return CapabilityOutcome(
                    {
                        "status": "blocked",
                        "capabilityStatus": "blocked",
                        "message": "AI가 빈 답변을 반환해서 완료로 처리하지 않았어. 다시 시도해줘.",
                        "runtimeStatus": result.status,
                    },
                    ExecutionStatus.BLOCKED,
                    ExecutionError(
                        code="assistant_empty_response",
                        message="Assistant provider returned an empty response",
                    ),
                )
            if result.status == "completed":
                return CapabilityOutcome({
                    "status": "completed", "capabilityStatus": "completed",
                    "message": result.summary,
                    "runtimeStatus": result.status, "events": result.events,
                })
            status = ExecutionStatus.FAILED if result.status == "failed" else ExecutionStatus.BLOCKED
            message = result.error or "실제 AI 응답을 사용할 수 없어."
            if "no local or chatgpt web provider" in message.casefold():
                message = "로컬 AI를 설치하거나 ChatGPT Web을 연결하면 EEEE가 대화할 수 있어."
            return CapabilityOutcome({
                "status": "blocked", "capabilityStatus": result.status,
                "message": message,
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
            "status": "blocked",
            "capabilityStatus": "blocked",
            "message": "로컬 AI를 설치하거나 ChatGPT Web을 연결하면 EEEE가 대화할 수 있어.",
            "context": envelope_context.assistant_context.model_dump(mode="json"),
        }, ExecutionStatus.BLOCKED, ExecutionError(
            code="no_ai_provider_configured",
            message="No local or ChatGPT Web provider is configured",
        ))


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


def _request_user_id(request: AssistantRequest) -> str:
    value = request.context.get("userId", "local-user")
    return value.strip() if isinstance(value, str) and value.strip() else "local-user"


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
        self.orchestrator = IseolOrchestrator(runner=self._execute_project)

    def plan(self, request: AssistantRequest, context: AssistantContext) -> CapabilityPlan:
        intake = NaturalLanguageIntake.parse(request.raw_text)
        requested_project_id = request.context.get("resumeProjectId")
        project_id = (
            requested_project_id
            if isinstance(requested_project_id, str) and requested_project_id.strip()
            else f"project-{uuid4().hex}"
        )
        root = self.settings.workspace_root.resolve()
        requested = request.context.get("workspace")
        workspace = Path(requested).resolve() if requested else root / "assistant" / project_id
        try:
            workspace.relative_to(root)
        except ValueError as exc:
            raise ValueError("Workspace must be inside the configured workspace root") from exc
        return CapabilityPlan(
            capability_id=self.descriptor.id, summary=request.raw_text,
            inputs={
                "text": request.raw_text,
                "projectId": project_id,
                "workspace": str(workspace),
                "projectIntent": intake.intent.model_dump(mode="json", by_alias=True),
                "requiresExternalApproval": intake.intent.requires_external_approval,
                "externalActions": [
                    action.model_dump(mode="json", by_alias=True)
                    for action in intake.intent.external_actions
                ],
                "approved": request.context.get("approved") is True,
                "clarificationQuestions": [
                    question.model_dump(mode="json", by_alias=True)
                    for question in intake.questions
                ],
                "userId": _request_user_id(request),
            },
            side_effect_level=self.descriptor.side_effect_level,
            requires_approval=self.descriptor.approval_level != "none",
        )

    def execute(self, plan: CapabilityPlan, envelope_context: EnvelopeContext) -> CapabilityOutcome:
        request = AssistantRequest(
            raw_text=str(plan.inputs["text"]),
            context={
                "projectId": str(plan.inputs["projectId"]),
                "workspace": str(plan.inputs["workspace"]),
                "projectIntent": plan.inputs.get("projectIntent"),
                "externalActionRequired": bool(plan.inputs.get("requiresExternalApproval")),
                "externalActions": plan.inputs.get("externalActions", []),
                "approved": plan.inputs.get("approved") is True,
                "clarificationQuestions": plan.inputs.get("clarificationQuestions", []),
                "userId": str(plan.inputs.get("userId", "local-user")),
            },
        )
        return self.orchestrator.run(request, envelope_context.assistant_context, envelope_context)

    def _execute_project(
        self,
        request: AssistantRequest,
        assistant_context: AssistantContext,
        envelope_context: EnvelopeContext,
    ) -> CapabilityOutcome:
        text = request.raw_text
        intent = ProjectIntent.model_validate(request.context.get("projectIntent"))
        user_id = _request_user_id(request)
        questions = [
            item for item in request.context.get("clarificationQuestions", [])
            if isinstance(item, dict)
        ]
        brief = intent.to_request_brief(questions=[])
        if questions:
            return CapabilityOutcome(
                {
                    "status": "needs_clarification",
                    "message": "프로젝트 종류와 원하는 결과물을 한 문장으로 더 알려줘.",
                    "questions": questions,
                    "intent": intent.model_dump(mode="json", by_alias=True),
                },
                ExecutionStatus.BLOCKED,
            )
        project_id = str(request.context["projectId"])
        try:
            project = self.store.get_project(project_id, user_id=_request_user_id(request))
            if Path(project.workspace).resolve() != Path(str(request.context["workspace"])).resolve():
                raise ValueError("Resumed project workspace does not match the accepted request")
        except KeyError:
            project = self.coordinator.create_project(
                project_id, brief.goal[:80], request.context["workspace"],
                user_id=_request_user_id(request),
            )
        try:
            existing_context = self.store.get_latest_request_context_for_project(project.id)
            if existing_context is not None:
                request_id, _workspace = existing_context
                state = self.coordinator.get_state(project.id, user_id=user_id)
                if state.request_id != request_id:
                    raise RuntimeError("Resumed project request state is inconsistent")
            else:
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
            project_brief = self.coordinator.build_project_brief(
                project.id, state.request_id, user_id=user_id
            )
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
                intent=intent,
                user_id=user_id,
            )
            agent_graph = _read_agent_graph(provisioned.execution_plan_path)
            agent_execution_report = None
            if self.agent_runtime is not None and agent_graph.get("agents"):
                agent_execution_report = AgentGraphExecutor(
                    runtime=self.agent_runtime,
                    trust_pipeline=self.coordinator.trust_pipeline,
                    workspace=Path(project.workspace),
                    max_parallelism=getattr(self.agent_runtime, "max_parallelism", 3),
                    checkpoint_path=Path(project.workspace) / ".gleave" / "iseol-checkpoint.json",
                ).execute(AgentGraph.model_validate(agent_graph), _child)
                _persist_agent_execution_report(
                    Path(provisioned.execution_plan_path) if provisioned.execution_plan_path else None,
                    Path(project.workspace) / "PROJECT_LOG.md",
                    agent_execution_report.model_dump(mode="json", by_alias=True),
                )
                if agent_execution_report.status != "completed":
                    blocked_report = _write_final_quality_report(
                        self.store,
                        project.workspace,
                        project.id,
                        project.revision,
                        state.request_id,
                        intent,
                        provisioned.execution_plan_path,
                        agent_graph,
                        {},
                        {
                            "decision": "BLOCKED",
                            "receiptId": None,
                            "claimLatchReportId": None,
                        },
                        user_id=user_id,
                    )
                    profile = self.store.get_project_profile(project.id, user_id=user_id)
                    return CapabilityOutcome(
                        {
                            "status": "blocked",
                            "message": "ISEOL specialist agent graph did not pass all handoff gates",
                            "projectId": project.id,
                            "projectRevision": project.revision,
                            "templateId": intent.template_id,
                            "assumptions": list(intent.assumptions),
                            "projectProfile": profile.model_dump(mode="json"),
                            "executionPlanPath": provisioned.execution_plan_path,
                            "planningSessionId": planning_handoff.planning_session_id,
                            "planningHandoffId": planning_handoff.handoff_id,
                            "agentGraph": agent_graph,
                            "missingExtensions": list(agent_graph.get("context", {}).get("missingExtensions", []))
                            if isinstance(agent_graph.get("context"), dict) else [],
                            "agentExecutionReport": agent_execution_report.model_dump(mode="json", by_alias=True),
                            "finalReportPath": profile.quality_report_path,
                            "finalGrade": blocked_report.grade,
                            "finalScore": blocked_report.score,
                            "finalBlockers": list(blocked_report.blockers),
                            "finalLimitations": list(blocked_report.limitations),
                        },
                        ExecutionStatus.BLOCKED,
                        ExecutionError(code="agent_graph_blocked", message="Agent graph handoff was blocked"),
                    )
            todo_run = None
            web_run = None
            claim_latch = {"decision": "BLOCKED", "receiptId": None, "claimLatchReportId": None}
            memory_records = []
            # Keep the original user utterance in the product-type decision.
            # The parsed goal is intentionally normalized and can vary by
            # locale/parser implementation; a direct request such as
            # "Todo 앱 만들어줘" must never skip the verified Todo runner.
            web_todo = intent.template_id == "todo_app" and any(
                marker in text.casefold()
                for marker in ("웹", "website", "web app", "webapp", "홈페이지", "사이트")
            )
            if intent.template_id == "todo_app" and not web_todo or (
                intent.template_id is None and is_todo_request(text, [brief.goal, brief.target_type, *brief.acceptance_criteria])
            ):
                prepared = self.provisioner.todo_runner.prepare(
                    project_id=project.id,
                    project_revision=project.revision,
                    workspace=project.workspace,
                    acceptance_criteria=intent.acceptance_criteria,
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
                    memory_records = self.coordinator.record_verified_project_outcome(
                        outcome, user_id=user_id
                    )
            elif brief.runtime_profile == "web_app":
                prepared = self.provisioner.web_runner.prepare(
                    project_id=project.id,
                    project_revision=project.revision,
                    workspace=project.workspace,
                    template_id=intent.template_id or "generic_web",
                    acceptance_criteria=intent.acceptance_criteria,
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
            final_report = None
            if todo_run is not None or web_run is not None:
                qa_report_path = Path(
                    todo_run.qa_report_path if todo_run is not None else web_run.qa_report_path
                )
                qa_report = _read_json_object(qa_report_path)
                execution_plan = _quality_plan(
                    Path(provisioned.execution_plan_path) if provisioned.execution_plan_path else None,
                    project_id=project.id,
                    project_revision=project.revision,
                    request_id=state.request_id,
                    intent=intent,
                    agent_graph=agent_graph,
                )
                final_report = _write_final_quality_report(
                    self.store,
                    project.workspace,
                    project.id,
                    project.revision,
                    state.request_id,
                    intent,
                    provisioned.execution_plan_path,
                    agent_graph,
                    qa_report,
                    claim_latch,
                    execution_plan=execution_plan,
                    user_id=user_id,
                )
            document_execution_id = None
            if self.document_service is not None:
                def sync_document(_document: ExecutionEnvelope) -> CapabilityOutcome:
                    result = self.document_service.sync(provisioned.profile, user_id=user_id)
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
            profile = self.store.get_project_profile(project.id, user_id=user_id)
            missing = sorted(binding.connector_id for binding in profile.connectors
                             if binding.state in {"awaiting_configuration", "planned"})
            quality_status = (
                web_run.status if web_run is not None
                else todo_run.status if todo_run is not None
                else None
            )
            missing_extensions = list(agent_graph.get("context", {}).get("missingExtensions", [])) \
                if isinstance(agent_graph.get("context"), dict) else []
            execution_status = _project_execution_status(
                quality_status=quality_status,
                final_blockers=list(final_report.blockers) if final_report is not None else [],
                missing_extensions=missing_extensions,
            )
            project_status = execution_status.value
            return CapabilityOutcome({
                "status": project_status,
                "message": "Project Runtime이 생성되었고 외부 연결 상태를 확인해야 해.",
                "projectId": project.id, "projectProfile": profile.model_dump(mode="json", by_alias=True),
                "templateId": intent.template_id,
                "assumptions": list(intent.assumptions),
                "missingConnectors": missing, "documentExecutionId": document_execution_id,
                "executionPlanPath": provisioned.execution_plan_path,
                "agentGraph": agent_graph,
                "missingExtensions": missing_extensions,
                "agentExecutionReport": agent_execution_report.model_dump(mode="json", by_alias=True)
                if agent_execution_report is not None else None,
                "planningSessionId": planning_handoff.planning_session_id,
                "planningHandoffId": planning_handoff.handoff_id,
                "qaReportPath": (web_run.qa_report_path if web_run is not None else todo_run.qa_report_path if todo_run is not None else None),
                "releaseManifestPath": (web_run.release_manifest_path if web_run is not None else todo_run.release_manifest_path if todo_run is not None else None),
                "gitBranch": (web_run.git_branch if web_run is not None else todo_run.git_branch if todo_run is not None else None),
                "gitCommit": (web_run.git_commit if web_run is not None else todo_run.git_commit if todo_run is not None else None),
                "qualityStatus": quality_status,
                "qualityReason": (web_run.reason if web_run is not None else todo_run.reason if todo_run is not None else None),
                "finalReportPath": profile.quality_report_path,
                "finalGrade": final_report.grade if final_report is not None else None,
                "finalScore": final_report.score if final_report is not None else None,
                "finalBlockers": list(final_report.blockers) if final_report is not None else [],
                "finalLimitations": list(final_report.limitations) if final_report is not None else [],
                "memoryCandidateIds": [record.id for record in memory_records],
            }, execution_status)

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


def _project_execution_status(
    *,
    quality_status: str | None,
    final_blockers: list[str],
    missing_extensions: list[str],
) -> ExecutionStatus:
    """Keep durable project state blocked until every release gate is evidenced."""

    if missing_extensions or final_blockers:
        return ExecutionStatus.BLOCKED
    if quality_status is not None and quality_status != "PASS":
        return ExecutionStatus.BLOCKED
    return ExecutionStatus.COMPLETED


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


def _read_json_object(path: Path) -> dict[str, Any]:
    """Read a generated JSON artifact without turning a missing artifact into evidence."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _quality_plan(
    path: Path | None,
    *,
    project_id: str,
    project_revision: str,
    request_id: str,
    intent: ProjectIntent,
    agent_graph: dict[str, Any],
) -> ProjectExecutionPlan:
    """Normalize the persisted plan before the final evaluator consumes it.

    The Node compatibility planner may omit native fields, so the evaluator
    always derives phases and extension state from the native graph when the
    persisted JSON is incomplete.  This keeps the final report deterministic
    without treating an adapter's partial output as proof of completion.
    """

    value = _read_json_object(path) if path is not None else {}
    graph_context = agent_graph.get("context") if isinstance(agent_graph.get("context"), dict) else {}
    agents = agent_graph.get("agents") if isinstance(agent_graph.get("agents"), list) else []
    phases = list(dict.fromkeys(
        str(agent.get("phase"))
        for agent in agents
        if isinstance(agent, dict) and isinstance(agent.get("phase"), str) and agent.get("phase")
    ))
    tasks = value.get("tasks") if isinstance(value.get("tasks"), list) else [
        {
            "id": agent.get("taskId", agent.get("id")),
            "agentId": agent.get("id"),
            "phase": agent.get("phase"),
            "status": "planned",
        }
        for agent in agents
        if isinstance(agent, dict)
    ]
    selected = value.get("selectedExtensions")
    missing = value.get("missingExtensions")
    return ProjectExecutionPlan(
        projectId=project_id,
        projectRevision=project_revision,
        requestId=request_id,
        intent=intent,
        phases=phases,
        tasks=[item for item in tasks if isinstance(item, dict)],
        selectedExtensions=(
            [str(item) for item in selected if isinstance(item, str)]
            if isinstance(selected, list)
            else [str(item) for item in graph_context.get("selectedExtensions", []) if isinstance(item, str)]
        ),
        missingExtensions=(
            [str(item) for item in missing if isinstance(item, str)]
            if isinstance(missing, list)
            else [str(item) for item in graph_context.get("missingExtensions", []) if isinstance(item, str)]
        ),
        externalActions=list(intent.external_actions),
    )


def _write_final_quality_report(
    store: SQLiteStore,
    workspace: str,
    project_id: str,
    project_revision: str,
    request_id: str,
    intent: ProjectIntent,
    plan_path: str | None,
    agent_graph: dict[str, Any],
    qa_report: dict[str, Any],
    claim_latch: dict[str, Any],
    *,
    execution_plan: ProjectExecutionPlan | None = None,
    user_id: str = "local-user",
):
    plan = execution_plan or _quality_plan(
        Path(plan_path) if plan_path else None,
        project_id=project_id,
        project_revision=project_revision,
        request_id=request_id,
        intent=intent,
        agent_graph=agent_graph,
    )
    report = ProjectQualityEvaluator().evaluate(
        Path(workspace), intent, plan, qa_report, claim_latch,
    )
    profile = store.get_project_profile(project_id, user_id=user_id)
    store.save_project_profile(profile.model_copy(update={
        "quality_report_path": str(Path(workspace) / "FINAL-QUALITY-REPORT.json"),
    }))
    return report


def _persist_agent_execution_report(
    plan_path: Path | None,
    log_path: Path,
    report: dict[str, Any],
) -> None:
    """Persist specialist handoffs beside the plan and human-readable log."""
    if plan_path is not None and plan_path.is_file():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if not isinstance(plan, dict):
            raise ValueError("execution-plan.json must contain an object")
        plan["agentExecutionReport"] = report
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    agents = report.get("agents", [])
    lines = [
        "",
        "## ISEOL specialist execution",
        f"- Graph: `{report.get('graphVersion', 'unknown')}`",
        f"- Status: `{report.get('status', 'unknown')}`",
    ]
    for agent in agents if isinstance(agents, list) else []:
        if not isinstance(agent, dict):
            continue
        evidence = ", ".join(str(item) for item in agent.get("evidenceIds", [])) or "none"
        changed = ", ".join(str(item) for item in agent.get("changedFiles", [])) or "none"
        lines.extend([
            f"- {agent.get('agentId', 'unknown')}: {agent.get('status', 'unknown')} — {agent.get('reason', '')}",
            f"  - evidence: {evidence}",
            f"  - changed files: {changed}",
        ])
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
