"""EEEE capability selection, execution policy, durable lifecycle, and context."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.assistant.models import AssistantContext, AssistantRequest, CapabilitySelection
from app.agent.protocol import AgentRuntime
from app.assistant.router import CapabilityRouter
from app.config import Settings
from app.contracts import ApprovalState, EventEnvelope, ExecutionEnvelope, ExecutionError, ExecutionStatus, LocalEventBus, SideEffectLevel
from app.coordinator.service import Coordinator
from app.kernel.capabilities import CapabilityOutcome, EnvelopeContext, GeneralConversationCapability, LocalPlanningCapability, ProjectExecutionCapability, UserPreferenceCapability
from app.memory.store import MemoryStore
from app.project_runtime.provisioner import ProjectProvisioner
from app.planning.service import PlanningService
from app.runtime.store import ExecutionStore, StaleProjectRevision
from app.storage.sqlite import SQLiteStore
from app.trust.gate import TrustGate
from app.plugins.host import PluginHost


class KernelService:
    def __init__(
        self, *, router: CapabilityRouter, coordinator: Coordinator, store: SQLiteStore,
        settings: Settings, provisioner: ProjectProvisioner, memory: MemoryStore | None = None,
        trust_gate: TrustGate | None = None, event_bus: LocalEventBus | None = None,
        event_publisher: Callable[[str, dict[str, object]], object] | None = None,
        document_service: Any | None = None, planning_service: PlanningService | None = None,
        agent_runtime: AgentRuntime | None = None, plugin_host: PluginHost | None = None,
    ) -> None:
        self.router = router
        self.coordinator = coordinator
        self.store = store
        self.memory = memory or coordinator.memory
        self.trust_gate = trust_gate or coordinator.trust_gate or TrustGate(None, mode="advisory")
        self.plugin_host = plugin_host
        self.executions = ExecutionStore(store)
        planning_service = planning_service or PlanningService(store)
        self.event_bus = event_bus or LocalEventBus()
        if event_publisher is not None:
            self.event_bus.subscribe(lambda event: event_publisher(
                event.event_type, event.model_dump(mode="json")["payload"],
            ))
        for descriptor in router.registry.list():
            if router.registry.resolve(descriptor.id).handler is not None:
                continue
            if descriptor.id == "project-execution":
                handler = ProjectExecutionCapability(
                    descriptor, coordinator=coordinator, store=store, settings=settings,
                    provisioner=provisioner, document_service=document_service,
                    planning_service=planning_service,
                    agent_runtime=agent_runtime,
                )
            elif descriptor.id == "user-preference":
                handler = UserPreferenceCapability(descriptor, coordinator)
            elif descriptor.id == "general-conversation":
                handler = GeneralConversationCapability(descriptor)
            elif descriptor.id in {"personal-secretary", "knowledge-documents", "presence"}:
                handler = LocalPlanningCapability(descriptor)
            else:
                continue
            router.registry.bind(descriptor.id, handler)

    def route(self, request: AssistantRequest, context: AssistantContext) -> ExecutionEnvelope:
        try:
            selection = self.router.select(request)
        except KeyError:
            selection = CapabilitySelection(status="needs_clarification", reasons=["Unknown capability"])
        capability_id = selection.capability_id or request.requested_capability or "assistant-routing"
        registered = self.router.registry.resolve(selection.capability_id) if selection.capability_id else None
        required_approval = registered is not None and registered.descriptor.approval_level != "none"
        approved = request.context.get("approved") is True
        parent = ExecutionEnvelope(
            execution_id=f"execution-{uuid4().hex}", request_id=f"assistant-request-{uuid4().hex}",
            capability_id=capability_id, tool_id="eeee.route", actor="EEEE",
            input={"request": request.model_dump(mode="json"), "context": context.model_dump(mode="json")},
            side_effect_level=registered.descriptor.side_effect_level if registered else SideEffectLevel.NONE,
            required_approval=required_approval,
            approval_state=(ApprovalState.APPROVED if approved else ApprovalState.AWAITING_APPROVAL)
            if required_approval else ApprovalState.NOT_REQUIRED,
        )
        self._record(parent)
        self._event(parent, "assistant.route.started", {
            "capabilityId": selection.capability_id, "selectionStatus": selection.status,
        })
        if registered is None:
            if selection.status == "plugin_required":
                return self._finish_route(parent, CapabilityOutcome(
                    {
                        "status": "plugin_required",
                        "message": selection.suggested_action or "필요한 플러그인을 설치하고 연결해줘.",
                        "pluginRequired": {
                            "id": selection.required_plugin_id,
                            "name": selection.required_plugin_name,
                            "permissions": selection.required_plugin_permissions,
                            "suggestedAction": selection.suggested_action,
                        },
                    },
                    ExecutionStatus.BLOCKED,
                ), selection)
            return self._finish_route(parent, CapabilityOutcome(
                {"status": "needs_clarification", "message": "어떤 작업 영역인지 조금 더 알려줘."},
                ExecutionStatus.BLOCKED,
            ), selection)
        stale_reason = self._context_identity_error(request)
        if stale_reason:
            return self._finish_route(parent, CapabilityOutcome(
                {"status": "blocked", "message": stale_reason}, ExecutionStatus.BLOCKED,
            ), selection)
        if required_approval and not approved:
            return self._finish_route(parent, CapabilityOutcome(
                {"status": "blocked", "message": "사용자 승인이 필요해."}, ExecutionStatus.AWAITING_APPROVAL,
            ), selection)
        parent = parent.transition(ExecutionStatus.RUNNING)
        self._record(parent)
        try:
            retrieved = self._retrieve_context(request, context)
            handler = registered.handler
            if handler is None:
                if self.plugin_host is None or not selection.capability_id.startswith("plugin:"):
                    raise RuntimeError("Capability implementation is unavailable")
                plugin_id, plugin_execution = self.plugin_host.invoke_capability(
                    selection.capability_id, {"text": request.raw_text, "context": request.context}
                )
                plugin_status = plugin_execution.status
                plugin_output = {
                    "status": "completed" if plugin_status == ExecutionStatus.COMPLETED else plugin_status.value,
                    "message": "플러그인 작업이 완료됐어." if plugin_status == ExecutionStatus.COMPLETED
                    else plugin_execution.error.message if plugin_execution.error else "플러그인 작업이 완료되지 않았어.",
                    "pluginId": plugin_id,
                    "pluginExecutionId": plugin_execution.execution_id,
                    "claimLatchPolicy": registered.descriptor.claim_latch_policy,
                }
                return self._finish_route(
                    parent,
                    CapabilityOutcome(
                        plugin_output,
                        ExecutionStatus.COMPLETED if plugin_status == ExecutionStatus.COMPLETED else ExecutionStatus.BLOCKED,
                    ),
                    selection,
                )
            plan = handler.plan(request, retrieved)
            if (plan.capability_id != registered.descriptor.id
                or plan.side_effect_level != parent.side_effect_level
                or plan.requires_approval != parent.required_approval):
                raise ValueError("Capability plan does not match the registered policy")
            if parent.side_effect_level == SideEffectLevel.EXTERNAL:
                trust = self._external_route_trust(parent, request)
                if trust is None or trust.decision != "PASS":
                    return self._finish_route(parent, CapabilityOutcome(
                        {"status": "blocked", "message": trust.reason if trust else "External action requires project identity",
                         "trust": trust.model_dump(mode="json") if trust else None}, ExecutionStatus.BLOCKED,
                    ), selection)
                parent = self._with_receipt(parent, trust.receipt_id)
                self.executions.save(parent)
            outcome = handler.execute(plan, EnvelopeContext(parent, retrieved, self.run_child))
        except Exception as exc:
            outcome = CapabilityOutcome(
                {"status": "blocked", "message": str(exc).strip() or type(exc).__name__},
                ExecutionStatus.FAILED, self._error(exc),
            )
        return self._finish_route(parent, outcome, selection)

    def run_child(
        self, *, parent: ExecutionEnvelope, project_id: str, revision: str, request_id: str,
        tool_id: str, inputs: dict[str, Any], side_effect_level: SideEffectLevel,
        operation: Callable[[ExecutionEnvelope], CapabilityOutcome], owns_trust_boundary: bool = False,
    ) -> ExecutionEnvelope:
        child = ExecutionEnvelope(
            execution_id=f"execution-{uuid4().hex}", request_id=request_id,
            project_id=project_id, project_revision=revision, capability_id=parent.capability_id,
            tool_id=tool_id, actor="ISEOL" if tool_id == "iseol" else "EEEE",
            input={**inputs, "parentExecutionId": parent.execution_id}, side_effect_level=side_effect_level,
        )
        self._record(child)
        trust = None
        try:
            child = child.transition(ExecutionStatus.RUNNING)
            self._record(child)
            if not owns_trust_boundary:
                trust = self.trust_gate.verify_action(
                    subject_id=child.execution_id, project_id=project_id, project_revision=revision,
                    action=tool_id, payload=child.model_dump(mode="json")["input"],
                )
                child = self._with_receipt(child, trust.receipt_id)
                self.executions.save(child)
            if trust is not None and (trust.decision == "BLOCKED" or (
                side_effect_level == SideEffectLevel.EXTERNAL and trust.decision != "PASS"
            )):
                outcome = CapabilityOutcome(
                    {"status": "blocked", "message": trust.reason}, ExecutionStatus.BLOCKED,
                )
            else:
                outcome = operation(child)
        except StaleProjectRevision as exc:
            return self._fail_stale_child(child.execution_id, exc)
        except Exception as exc:
            outcome = CapabilityOutcome(
                {"status": "blocked", "message": str(exc).strip() or type(exc).__name__},
                ExecutionStatus.FAILED, self._error(exc),
            )
        output = dict(outcome.output)
        if trust is not None:
            output["trust"] = trust.model_dump(mode="json")
        elif isinstance(output.get("trust"), dict):
            child = self._with_receipt(child, output["trust"].get("receipt_id"))
        child = child.transition(outcome.status, output=output, error=outcome.error)
        try:
            self._record(child)
        except StaleProjectRevision as exc:
            return self._fail_stale_child(child.execution_id, exc)
        return child

    def _fail_stale_child(self, execution_id: str, exc: StaleProjectRevision) -> ExecutionEnvelope:
        # Reload the persisted state: never attach evidence or receipts obtained
        # after the project revision changed, and never rewrite the fixed identity.
        stored = self.executions.get(execution_id)
        error = ExecutionError(code="stale_project_revision", message=str(exc))
        status = ExecutionStatus.FAILED if stored.status == ExecutionStatus.RUNNING else ExecutionStatus.BLOCKED
        failed = stored.transition(status, output={"status": "blocked", "message": error.message}, error=error)
        self._record(failed)
        return failed

    def _finish_route(
        self, parent: ExecutionEnvelope, outcome: CapabilityOutcome, selection: CapabilitySelection,
    ) -> ExecutionEnvelope:
        output = {**outcome.output, "selection": selection.model_dump(mode="json")}
        output["responseVerification"] = self._verify_response(parent, output)
        parent = parent.transition(outcome.status, output=output, error=outcome.error)
        self._record(parent)
        if output.get("projectId"):
            self._event(parent, "project.created", {
                "projectId": output["projectId"], "projectRevision": output.get("projectRevision"),
                "status": output.get("status"),
            })
        self._event(parent, "assistant.route.completed", {
            "status": output.get("status"), "capabilityId": selection.capability_id,
            "projectId": output.get("projectId"), "executionId": parent.execution_id,
        })
        return parent

    def _verify_response(self, parent: ExecutionEnvelope, output: dict[str, Any]) -> dict[str, Any]:
        """Attach a ClaimLatch decision to every assistant route response."""
        project_id = output.get("projectId")
        project_revision = output.get("projectRevision")
        if not isinstance(project_id, str) or not isinstance(project_revision, str):
            blocked = str(output.get("status", "")).lower() in {"blocked", "failed"}
            return {
                "decision": "BLOCKED" if blocked else "WARN",
                "reason": (
                    "Assistant response is blocked; ClaimLatch response verification cannot release it"
                    if blocked else
                    "ClaimLatch response verification requires project identity; response is advisory"
                ),
                "profile_version": self.trust_gate.profile_version,
                "subject_id": parent.execution_id,
            }
        claim = output.get("message") or output.get("status") or "Assistant route response"
        check = self.trust_gate.verify_claim(
            subject_id=parent.execution_id,
            project_id=project_id,
            project_revision=project_revision,
            claim=str(claim),
            action="assistant.response",
        )
        blocked = str(output.get("status", "")).lower() in {"blocked", "failed"}
        return {
            "decision": "BLOCKED" if blocked else check.decision,
            "reason": (
                f"Assistant response is blocked: {output.get('message', check.reason)}"
                if blocked else check.reason
            ),
            "profile_version": check.claim_latch_profile_version,
            "subject_id": parent.execution_id,
            "claim_latch_receipt_id": check.receipt_id,
            "claim_latch_report_id": check.report_id,
        }

    def _record(self, envelope: ExecutionEnvelope) -> None:
        event = self._make_event(envelope, f"execution.{envelope.status.value}", {
            "status": envelope.status.value, "toolId": envelope.tool_id,
            "parentExecutionId": envelope.input.get("parentExecutionId"),
        })
        self._publish(self.executions.record(envelope, event))

    def _event(self, envelope: ExecutionEnvelope, kind: str, payload: dict[str, Any]) -> None:
        self._publish(self.executions.append_event(self._make_event(envelope, kind, payload)))

    @staticmethod
    def _make_event(envelope: ExecutionEnvelope, kind: str, payload: dict[str, Any]) -> EventEnvelope:
        return EventEnvelope(
            event_type=kind, execution_id=envelope.execution_id, request_id=envelope.request_id,
            project_id=envelope.project_id, project_revision=envelope.project_revision, payload=payload,
        )

    def _publish(self, durable: EventEnvelope) -> None:
        self.event_bus.publish(EventEnvelope.model_validate({
            **durable.model_dump(), "cursor": None,
            "payload": {**durable.payload, "durableCursor": durable.cursor},
        }))

    def _retrieve_context(self, request: AssistantRequest, supplied: AssistantContext) -> AssistantContext:
        memories = self.memory.search(request.raw_text)
        persistent_preferences = {
            key: record.content
            for key, record in self.memory.search_user_preferences().items()
        }
        return AssistantContext(
            memory_ids=list(dict.fromkeys([*supplied.memory_ids, *(item.id for item in memories)])),
            qa_baseline_ids=list(dict.fromkeys([
                *supplied.qa_baseline_ids, *(item.id for item in memories if item.kind in {"qa_rule", "regression_rule"}),
            ])), user_preferences={**persistent_preferences, **supplied.user_preferences},
        )

    def _context_identity_error(self, request: AssistantRequest) -> str | None:
        project_id = request.context.get("projectId")
        revision = request.context.get("projectRevision")
        if project_id is None and revision is None:
            return None
        if not isinstance(project_id, str) or not isinstance(revision, str):
            return "Project context requires projectId and projectRevision together"
        try:
            current = self.store.get_project(project_id)
        except KeyError:
            return "Project context is unavailable"
        return None if current.revision == revision else "stale project revision in assistant context"

    def _external_route_trust(self, parent: ExecutionEnvelope, request: AssistantRequest):
        project_id, revision = request.context.get("projectId"), request.context.get("projectRevision")
        if project_id is None or revision is None:
            return None
        return self.trust_gate.verify_action(
            subject_id=parent.execution_id, project_id=project_id, project_revision=revision,
            action=parent.capability_id, payload=parent.model_dump(mode="json")["input"],
        )

    @staticmethod
    def _with_receipt(envelope: ExecutionEnvelope, receipt: str | None) -> ExecutionEnvelope:
        if receipt is None:
            return envelope
        return ExecutionEnvelope.model_validate({**envelope.model_dump(), "claim_latch_receipt_id": receipt})

    @staticmethod
    def _error(exc: Exception) -> ExecutionError:
        return ExecutionError(
            code="invalid_request" if isinstance(exc, ValueError) else "capability_failed",
            message=str(exc).strip() or type(exc).__name__,
        )
