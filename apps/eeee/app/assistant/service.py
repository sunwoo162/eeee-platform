from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.assistant.models import AssistantContext, AssistantRequest, CapabilitySelection, ResponseVerification
from app.assistant.router import CapabilityRouter
from app.assistant.secretary import PersonalSecretary
from app.config import Settings
from app.coordinator.service import Coordinator
from app.conversations.models import MessageStatus
from app.conversations.store import ConversationStore
from app.project_runtime.models import ProjectProfile
from app.project_runtime.documents import ProjectDocumentService
from app.project_runtime.provisioner import ProjectProvisioner
from app.storage.sqlite import SQLiteStore
from app.kernel.service import KernelService
from app.memory.preferences import extract_implicit_preference
from app.assistant.background import BackgroundExecutionSupervisor


class AssistantRouteResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: Literal[
        "selected", "needs_clarification", "ready", "awaiting_configuration",
        "completed", "blocked", "unsupported", "plugin_required", "accepted",
    ]
    selection: CapabilitySelection
    message: str = Field(min_length=1)
    project_id: str | None = None
    project_profile: ProjectProfile | None = None
    template_id: str | None = Field(default=None, alias="templateId")
    missing_connectors: list[str] = Field(default_factory=list)
    missing_extensions: list[str] = Field(default_factory=list, alias="missingExtensions")
    execution_plan_path: str | None = Field(default=None, alias="executionPlanPath")
    planning_session_id: str | None = Field(default=None, alias="planningSessionId")
    planning_handoff_id: str | None = Field(default=None, alias="planningHandoffId")
    quality_status: str | None = Field(default=None, alias="qualityStatus")
    quality_reason: str | None = Field(default=None, alias="qualityReason")
    final_report_path: str | None = Field(default=None, alias="finalReportPath")
    quality_score: int | None = Field(default=None, alias="qualityScore", ge=0, le=100)
    quality_grade: str | None = Field(default=None, alias="qualityGrade")
    final_blockers: list[str] = Field(default_factory=list, alias="finalBlockers")
    final_limitations: list[str] = Field(default_factory=list, alias="finalLimitations")
    qa_report_path: str | None = Field(default=None, alias="qaReportPath")
    release_manifest_path: str | None = Field(default=None, alias="releaseManifestPath")
    git_branch: str | None = Field(default=None, alias="gitBranch")
    git_commit: str | None = Field(default=None, alias="gitCommit")
    response_verification: ResponseVerification
    required_plugin_id: str | None = None
    required_plugin_name: str | None = None
    required_plugin_permissions: list[str] = Field(default_factory=list)
    suggested_action: str | None = None
    plugin_id: str | None = None
    plugin_execution_id: str | None = None
    plugin_output: dict[str, object] | None = Field(default=None, alias="pluginOutput")
    reminder: dict[str, str] | None = None
    reminders: list[dict[str, str]] = Field(default_factory=list)
    document: dict[str, object] | None = None
    documents: list[dict[str, object]] = Field(default_factory=list)
    summary: str | None = None
    sources: list[dict[str, object]] = Field(default_factory=list)
    approval_required: bool = Field(default=False, alias="approvalRequired")
    approval_capability_id: str | None = Field(default=None, alias="approvalCapabilityId")
    approval_plugin_id: str | None = Field(default=None, alias="approvalPluginId")
    approval_side_effect_level: str | None = Field(default=None, alias="approvalSideEffectLevel")
    approval_request_id: str | None = Field(default=None, alias="approvalRequestId")
    job_id: str | None = Field(default=None, alias="jobId")
    # Expose the selected lane so the Desktop can show/debug the real route
    # instead of making the user guess whether a turn reached Web/GPT.
    provider: str | None = None
    request_id: str | None = Field(default=None, alias="requestId")


class AssistantService:
    """Compatibility facade for EEEE requests handled by the shared kernel."""

    def __init__(
        self,
        *,
        router: CapabilityRouter,
        coordinator: Coordinator,
        store: SQLiteStore,
        settings: Settings,
        provisioner: ProjectProvisioner,
        event_publisher: Callable[[str, dict[str, object]], object] | None = None,
        document_service: ProjectDocumentService | None = None,
        kernel: KernelService | None = None, agent_runtime=None,
        background_supervisor: BackgroundExecutionSupervisor | None = None,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self.router = router
        self.coordinator = coordinator
        self.store = store
        self.settings = settings
        self.provisioner = provisioner
        self.background_supervisor = background_supervisor
        self.conversation_store = conversation_store
        self.event_publisher = event_publisher
        self.document_service = document_service
        self.secretary = PersonalSecretary()
        self.kernel = kernel or KernelService(
            router=router, coordinator=coordinator, store=store, settings=settings,
            provisioner=provisioner, event_publisher=event_publisher,
            document_service=document_service, agent_runtime=agent_runtime,
            chatgpt_web_enabled=settings.chatgpt_web_enabled,
        )

    def route(
        self, text: str, workspace: str | None = None, *, requested_capability: str | None = None,
        conversation_id: str = "desktop-default", approved: bool = False,
        approval_request_id: str | None = None, request_id: str | None = None,
        user_id: str = "local-user",
    ) -> AssistantRouteResult:
        request_id = request_id.strip() if request_id else None
        request = AssistantRequest(
            raw_text=text,
            context={
                "workspace": workspace,
                "conversationId": conversation_id,
                "approved": approved,
                "userId": user_id,
            },
            requested_capability=requested_capability,
        )
        if self.background_supervisor is not None:
            selection = self.router.select(request)
            if selection.status == "selected" and selection.capability_id == "project-execution":
                existing_request_id = request_id
                if existing_request_id is None and self.conversation_store is not None:
                    existing_request_id = self.conversation_store.find_pending_route(
                        conversation_id, text, user_id=user_id
                    )
                if existing_request_id is not None:
                    existing_job = self.background_supervisor.find_by_request_id(
                        existing_request_id, user_id=user_id
                    )
                    if existing_job is not None:
                        job_status = str(existing_job.get("status"))
                        if job_status in {"queued", "running", "paused"}:
                            return self._accepted_background_result(
                                selection, existing_job, existing_request_id
                            )
                        if job_status == "completed" and isinstance(existing_job.get("result"), dict):
                            return AssistantRouteResult.model_validate(existing_job["result"])
                request_id = request_id or f"assistant-request-{uuid4().hex}"
                # Allocate the identity before the worker starts.  The same
                # value is persisted in the job input so a process restart or
                # manual retry resumes the original project instead of
                # creating a second one.
                project_id = f"project-{uuid4().hex}"

                def run_project() -> dict[str, object]:
                    self._prepare_background_attempt(
                        conversation_id, text, request_id, user_id=user_id
                    )
                    try:
                        result = self._route_sync(
                            text, workspace, requested_capability=requested_capability,
                            conversation_id=conversation_id, approved=approved, resume_project_id=project_id,
                            approval_request_id=approval_request_id, request_id=request_id,
                            user_id=user_id,
                        )
                    except Exception as exc:
                        self._remember_turn(
                            conversation_id,
                            text,
                            f"백그라운드 작업에 실패했어: {str(exc).strip() or type(exc).__name__}",
                            request_id=request_id,
                            status=MessageStatus.FAILED,
                            error_code="assistant_route_failed",
                            user_id=user_id,
                        )
                        self._record_route_lifecycle(
                            conversation_id, request_id, "failed",
                            error_code="assistant_route_failed", user_id=user_id,
                        )
                        raise
                    self._remember_turn(
                        conversation_id, text, result.message, request_id=request_id,
                        status=self._message_status_for_result(result),
                        provider=getattr(result, "provider", None),
                        user_id=user_id,
                    )
                    self._record_route_lifecycle(
                        conversation_id, request_id, self._route_status_for_result(result),
                        user_id=user_id,
                    )
                    return result.model_dump(mode="json")

                accepted_message = "프로젝트 작업을 백그라운드에서 시작했어. 진행 상황에서 확인할 수 있어."
                self._remember_turn(
                    conversation_id, text, accepted_message, request_id=request_id,
                    status=MessageStatus.PENDING,
                    user_id=user_id,
                )
                self._record_route_lifecycle(
                    conversation_id, request_id, "accepted", user_id=user_id
                )
                try:
                    job_id = self.background_supervisor.submit(
                        request_id,
                        run_project,
                        input_data={
                            "text": text,
                            "workspace": workspace,
                            "requestedCapability": requested_capability,
                            "conversationId": conversation_id,
                            "approved": approved,
                            "approvalRequestId": approval_request_id,
                            "requestId": request_id,
                            "projectId": project_id,
                            "userId": user_id,
                        },
                    )
                except Exception as exc:
                    failure_message = (
                        f"백그라운드 작업을 시작하지 못했어: "
                        f"{str(exc).strip() or type(exc).__name__}"
                    )
                    self._remember_turn(
                        conversation_id, text, failure_message, request_id=request_id,
                        status=MessageStatus.FAILED,
                        error_code="assistant_job_submit_failed",
                        user_id=user_id,
                    )
                    self._record_route_lifecycle(
                        conversation_id, request_id, "failed",
                        error_code="assistant_job_submit_failed",
                        user_id=user_id,
                    )
                    raise
                result = AssistantRouteResult(
                    status="accepted",
                    selection=selection,
                    message=accepted_message,
                    project_id=project_id,
                    job_id=job_id,
                    provider=None,
                    request_id=request_id,
                    response_verification=ResponseVerification(
                        decision="WARN",
                        reason="Project execution was accepted and is awaiting background verification",
                        profile_version=self.settings.claim_latch_profile_version,
                        subject_id=job_id,
                    ),
                )
                return result
        request_id = request_id or f"assistant-request-{uuid4().hex}"
        result = self._route_sync(
            text, workspace, requested_capability=requested_capability,
            conversation_id=conversation_id, approved=approved,
            approval_request_id=approval_request_id, request_id=request_id,
            user_id=user_id,
        )
        self._remember_turn(
            conversation_id,
            text,
            result.message,
            request_id=request_id,
            status=self._message_status_for_result(result),
            provider=getattr(result, "provider", None),
            user_id=user_id,
        )
        self._record_route_lifecycle(
            conversation_id, request_id, self._route_status_for_result(result),
            user_id=user_id,
        )
        return result

    def _accepted_background_result(
        self, selection: CapabilitySelection, job: dict[str, object], request_id: str
    ) -> AssistantRouteResult:
        input_data = job.get("input")
        input_data = input_data if isinstance(input_data, dict) else {}
        project_id = input_data.get("projectId")
        return AssistantRouteResult(
            status="accepted",
            selection=selection,
            message="이미 같은 프로젝트 작업을 백그라운드에서 진행 중이야.",
            project_id=project_id if isinstance(project_id, str) else None,
            job_id=str(job.get("jobId")) if job.get("jobId") else None,
            request_id=request_id,
            response_verification=ResponseVerification(
                decision="WARN",
                reason="A duplicate request was attached to the existing background job",
                profile_version=self.settings.claim_latch_profile_version,
                subject_id=request_id,
            ),
        )

    def _route_sync(
        self, text: str, workspace: str | None = None, *, requested_capability: str | None = None,
        conversation_id: str = "desktop-default", approved: bool = False,
        approval_request_id: str | None = None,
        resume_project_id: str | None = None, request_id: str | None = None,
        user_id: str = "local-user",
    ) -> AssistantRouteResult:
        implicit_preference = extract_implicit_preference(text)
        if implicit_preference is not None:
            self.coordinator.remember_user_preference(
                implicit_preference.key,
                implicit_preference.value,
                scope={"source": "automatic_learning"},
                user_id=user_id,
            )
        for key, value in self.secretary.rememberable_facts(text):
            self.coordinator.remember_user_preference(
                key,
                value,
                scope={"source": "automatic_learning"},
                user_id=user_id,
            )
        envelope = self.kernel.route(
            AssistantRequest(
                raw_text=text,
                context={
                    "workspace": workspace,
                    "conversationId": conversation_id,
                    "approved": approved,
                    "userId": user_id,
                    **({"requestId": request_id} if request_id else {}),
                    **({"approvalRequestId": approval_request_id} if approval_request_id else {}),
                    **({"resumeProjectId": resume_project_id} if resume_project_id else {}),
                },
                             requested_capability=requested_capability),
            AssistantContext(),
        )
        if envelope.error is not None and envelope.error.code == "invalid_request":
            raise ValueError(envelope.error.message)
        output = envelope.model_dump(mode="json")["output"] or {}
        response_verification = ResponseVerification.model_validate(
            output.get("responseVerification", {
                "decision": "WARN",
                "reason": "Response verification metadata is missing",
                "profile_version": self.settings.claim_latch_profile_version,
                "subject_id": envelope.execution_id,
            })
        )
        quality_status = output.get("qualityStatus")
        # A project-free conversation normally has ClaimLatch WARN because
        # there is no project identity to bind to. WARN is advisory; BLOCKED
        # is the terminal decision that must prevent a completed response.
        completed_locally = quality_status == "PASS" and response_verification.decision != "BLOCKED"
        missing_connectors = output.get("missingConnectors", [])
        project_profile = output.get("projectProfile") or {}
        requires_external_configuration = (
            isinstance(project_profile, dict)
            and project_profile.get("runtimeProfile") == "web_app"
            and project_profile.get("templateId") != "todo_app"
        )
        status = (
            "awaiting_configuration"
            if completed_locally and missing_connectors and requires_external_configuration
            else "completed"
            if completed_locally
            else output.get("status", "blocked")
        )
        message = output.get("message", "요청을 완료하지 못했어.")
        if completed_locally:
            message = "로컬 프로젝트가 생성되고 QA/ClaimLatch 검증을 통과했어. 외부 플러그인은 선택적으로 연결할 수 있어."
        elif status == "completed" and (
            response_verification.decision == "BLOCKED" or quality_status is not None
        ):
            status = "blocked"
            message = (
                response_verification.reason
                if response_verification.decision != "PASS"
                else "완료 검증 증거가 없어."
            )
        provider = None
        events = output.get("events")
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                event_type = event.get("type")
                if event_type == "provider.selected" and isinstance(event.get("provider"), str):
                    provider = event["provider"]
                elif event_type == "local.conversation" and isinstance(event.get("provider"), str):
                    provider = event["provider"]
        return AssistantRouteResult(
            status=status,
            selection=CapabilitySelection.model_validate(output["selection"]),
            message=message,
            project_id=output.get("projectId"),
            project_profile=output.get("projectProfile"),
            template_id=(
                output.get("templateId")
                or project_profile.get("templateId")
                if isinstance(project_profile, dict)
                else output.get("templateId")
            ),
            missing_connectors=missing_connectors,
            missing_extensions=output.get("missingExtensions", []) if isinstance(output.get("missingExtensions", []), list) else [],
            execution_plan_path=output.get("executionPlanPath"),
            planning_session_id=output.get("planningSessionId"),
            planning_handoff_id=output.get("planningHandoffId"),
            quality_status=quality_status,
            quality_reason=output.get("qualityReason"),
            final_report_path=output.get("finalReportPath"),
            quality_score=output.get("finalScore") if isinstance(output.get("finalScore"), int) else None,
            quality_grade=output.get("finalGrade") if isinstance(output.get("finalGrade"), str) else None,
            final_blockers=output.get("finalBlockers", []) if isinstance(output.get("finalBlockers", []), list) else [],
            final_limitations=output.get("finalLimitations", []) if isinstance(output.get("finalLimitations", []), list) else [],
            qa_report_path=output.get("qaReportPath"),
            release_manifest_path=output.get("releaseManifestPath"),
            git_branch=output.get("gitBranch"),
            git_commit=output.get("gitCommit"),
            required_plugin_id=output.get("pluginRequired", {}).get("id") if isinstance(output.get("pluginRequired"), dict) else None,
            required_plugin_name=output.get("pluginRequired", {}).get("name") if isinstance(output.get("pluginRequired"), dict) else None,
            required_plugin_permissions=output.get("pluginRequired", {}).get("permissions", []) if isinstance(output.get("pluginRequired"), dict) else [],
            suggested_action=output.get("pluginRequired", {}).get("suggestedAction") if isinstance(output.get("pluginRequired"), dict) else None,
            plugin_id=output.get("pluginId"),
            plugin_execution_id=output.get("pluginExecutionId"),
            plugin_output=output.get("pluginOutput") if isinstance(output.get("pluginOutput"), dict) else None,
            reminder=output.get("reminder") if isinstance(output.get("reminder"), dict) else None,
            reminders=output.get("reminders", []) if isinstance(output.get("reminders", []), list) else [],
            document=output.get("document") if isinstance(output.get("document"), dict) else None,
            documents=output.get("documents", []) if isinstance(output.get("documents", []), list) else [],
            summary=output.get("summary") if isinstance(output.get("summary"), str) else None,
            sources=output.get("sources", []) if isinstance(output.get("sources", []), list) else [],
            approval_required=output.get("approvalRequired") is True,
            approval_capability_id=output.get("approvalCapabilityId"),
            approval_plugin_id=output.get("approvalPluginId"),
            approval_side_effect_level=output.get("approvalSideEffectLevel"),
            approval_request_id=output.get("approvalRequestId"),
            provider=provider,
            request_id=request_id,
            response_verification=response_verification,
        )

    def _record_route_lifecycle(
        self, conversation_id: str, request_id: str | None, status: str, *,
        error_code: str | None = None, user_id: str = "local-user",
    ) -> None:
        if self.conversation_store is None or request_id is None:
            return
        if error_code is None and status not in {"accepted", "pending", "completed"}:
            error_code = "assistant_route_failed"
        self.conversation_store.record_route_lifecycle(
            conversation_id, request_id, status, error_code=error_code, user_id=user_id
        )

    def _remember_turn(
        self, conversation_id: str, user_text: str, assistant_text: str,
        *, request_id: str | None = None,
        status: MessageStatus = MessageStatus.COMPLETED,
        provider: str | None = None,
        model: str | None = None,
        error_code: str | None = None,
        user_id: str = "local-user",
    ) -> None:
        if self.conversation_store is not None and request_id is not None:
            self.conversation_store.record_route_turn(
                conversation_id,
                user_id=user_id,
                user_content=user_text,
                assistant_content=assistant_text,
                request_id=request_id,
                assistant_status=status,
                provider=provider,
                model=model,
                error_code=error_code,
            )
            # ConversationStore is the canonical transcript.  Do not mirror
            # route turns into the legacy memory table: background completion
            # would otherwise create a second physical history and make the
            # provider/context boundary ambiguous.  MemoryStore remains the
            # compatibility path for embedded callers that have not supplied
            # a canonical conversation store.
            return
        memory_store = getattr(self.coordinator, "memory", None)
        if memory_store is None:
            return
        memory_store.append_conversation_turn(
            conversation_id, "user", user_text, request_id=request_id, user_id=user_id,
        )
        memory_store.append_conversation_turn(
            conversation_id, "assistant", assistant_text,
            request_id=request_id, user_id=user_id,
        )

    @staticmethod
    def _message_status_for_result(result: AssistantRouteResult | object) -> MessageStatus:
        """Translate route lifecycle into the canonical message lifecycle.

        ``AssistantRouteResult.status`` describes whether EEEE fulfilled the
        request, while ``MessageStatus`` describes the persisted assistant
        message.  A non-empty explanation for a blocked or unsupported route
        is still a failed request, not a completed one.
        """

        route_status = AssistantService._route_status_for_result(result)

        if route_status == "accepted":
            return MessageStatus.PENDING
        if route_status == "completed":
            return MessageStatus.COMPLETED
        return MessageStatus.FAILED

    @staticmethod
    def _route_status_for_result(result: AssistantRouteResult | object) -> str:
        route_status = getattr(result, "status", None)
        if isinstance(route_status, str):
            return route_status
        dump = getattr(result, "model_dump", None)
        payload = dump(mode="json") if callable(dump) else {}
        value = payload.get("status") if isinstance(payload, dict) else None
        return value if isinstance(value, str) else "completed"

    def get_project_profile(
        self, project_id: str, *, user_id: str = "local-user"
    ) -> ProjectProfile:
        return self.store.get_project_profile(project_id, user_id=user_id)

    def get_background_job(self, job_id: str, *, user_id: str = "local-user") -> dict[str, object]:
        if self.background_supervisor is None:
            raise KeyError(f"Assistant job not found: {job_id}")
        return self.background_supervisor.get(job_id, user_id=user_id)

    def list_background_jobs(
        self, *, status: str | None = None, limit: int = 100, user_id: str = "local-user",
    ) -> list[dict[str, object]]:
        if self.background_supervisor is None:
            return []
        return self.background_supervisor.list_jobs(status=status, limit=limit, user_id=user_id)

    def pause_background_job(self, job_id: str, *, user_id: str = "local-user") -> dict[str, object]:
        if self.background_supervisor is None:
            raise KeyError(f"Assistant job not found: {job_id}")
        return self.background_supervisor.pause(job_id, user_id=user_id)

    def cancel_background_job(self, job_id: str, *, user_id: str = "local-user") -> dict[str, object]:
        if self.background_supervisor is None:
            raise KeyError(f"Assistant job not found: {job_id}")
        return self.background_supervisor.cancel(job_id, user_id=user_id)

    def resume_background_job(self, job_id: str, *, user_id: str = "local-user") -> dict[str, object]:
        if self.background_supervisor is None:
            raise KeyError(f"Assistant job not found: {job_id}")
        return self.background_supervisor.resume(
            job_id, self._background_operation_factory, user_id=user_id
        )

    def retry_background_job(self, job_id: str, *, user_id: str = "local-user") -> dict[str, object]:
        if self.background_supervisor is None:
            raise KeyError(f"Assistant job not found: {job_id}")
        return self.background_supervisor.retry(
            job_id, self._background_operation_factory, user_id=user_id
        )

    def resume_background_jobs(self) -> list[str]:
        if self.background_supervisor is None:
            return []

        return self.background_supervisor.resume_pending(self._background_operation_factory)

    def _background_operation_factory(self, job: dict[str, object]):
        input_data = job.get("input", {})
        input_data = input_data if isinstance(input_data, dict) else {}
        text = input_data.get("text")
        workspace = input_data.get("workspace")
        requested_capability = input_data.get("requestedCapability")
        conversation_id = input_data.get("conversationId")
        approved = input_data.get("approved")
        approval_request_id = input_data.get("approvalRequestId")
        user_id = input_data.get("userId")
        project_id = input_data.get("projectId")
        request_id = input_data.get("requestId")
        if not isinstance(text, str) or not text.strip():
            return lambda: {"status": "blocked", "message": "백그라운드 작업 요청 원문이 없어 재개할 수 없어."}
        resolved_conversation_id = conversation_id if isinstance(conversation_id, str) else "desktop-default"
        resolved_request_id = request_id if isinstance(request_id, str) else None
        resolved_user_id = user_id if isinstance(user_id, str) and user_id.strip() else "local-user"

        def run() -> dict[str, object]:
            self._prepare_background_attempt(
                resolved_conversation_id, text, resolved_request_id,
                user_id=resolved_user_id,
            )
            try:
                result = self._route_sync(
                    text,
                    workspace if isinstance(workspace, str) else None,
                    requested_capability=requested_capability if isinstance(requested_capability, str) else None,
                    conversation_id=resolved_conversation_id,
                    approved=approved is True,
                    approval_request_id=approval_request_id if isinstance(approval_request_id, str) else None,
                    resume_project_id=project_id if isinstance(project_id, str) else None,
                    request_id=resolved_request_id,
                    user_id=resolved_user_id,
                )
            except Exception as exc:
                self._remember_turn(
                    resolved_conversation_id,
                    text,
                    f"백그라운드 작업에 실패했어: {str(exc).strip() or type(exc).__name__}",
                    request_id=resolved_request_id,
                    status=MessageStatus.FAILED,
                    error_code="assistant_route_failed",
                    user_id=resolved_user_id,
                )
                self._record_route_lifecycle(
                    resolved_conversation_id, resolved_request_id, "failed",
                    error_code="assistant_route_failed",
                    user_id=resolved_user_id,
                )
                raise
            self._remember_turn(
                resolved_conversation_id,
                text,
                result.message,
                request_id=resolved_request_id,
                status=self._message_status_for_result(result),
                provider=getattr(result, "provider", None),
                user_id=resolved_user_id,
            )
            self._record_route_lifecycle(
                resolved_conversation_id, resolved_request_id,
                self._route_status_for_result(result),
                user_id=resolved_user_id,
            )
            return result.model_dump(mode="json")

        return run

    def _prepare_background_attempt(
        self, conversation_id: str, user_text: str, request_id: str | None,
        *, user_id: str = "local-user",
    ) -> None:
        """Re-open canonical state when a failed job is retried.

        The supervisor reuses the durable job and request id on retry.  A
        terminal canonical request therefore needs an explicit new attempt
        before the worker can publish a successful result; otherwise the job
        and transcript can disagree permanently.
        """

        if self.conversation_store is None or request_id is None:
            return
        try:
            request = self.conversation_store.get_request(request_id)
        except KeyError:
            return
        if request.state.value not in {"failed", "cancelled", "interrupted"}:
            return
        self._remember_turn(
            conversation_id,
            user_text,
            "백그라운드 작업을 다시 시도하고 있어.",
            request_id=request_id,
            status=MessageStatus.PENDING,
            error_code=None,
            user_id=user_id,
        )
        self._record_route_lifecycle(
            conversation_id, request_id, "accepted", user_id=user_id
        )

