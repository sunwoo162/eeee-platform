from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.assistant.models import AssistantContext, AssistantRequest, CapabilitySelection, ResponseVerification
from app.assistant.router import CapabilityRouter
from app.config import Settings
from app.coordinator.service import Coordinator
from app.project_runtime.models import ProjectProfile
from app.project_runtime.documents import ProjectDocumentService
from app.project_runtime.provisioner import ProjectProvisioner
from app.storage.sqlite import SQLiteStore
from app.kernel.service import KernelService


class AssistantRouteResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: Literal[
        "selected", "needs_clarification", "ready", "awaiting_configuration",
        "completed", "blocked",
    ]
    selection: CapabilitySelection
    message: str = Field(min_length=1)
    project_id: str | None = None
    project_profile: ProjectProfile | None = None
    missing_connectors: list[str] = Field(default_factory=list)
    execution_plan_path: str | None = Field(default=None, alias="executionPlanPath")
    planning_session_id: str | None = Field(default=None, alias="planningSessionId")
    planning_handoff_id: str | None = Field(default=None, alias="planningHandoffId")
    quality_status: str | None = Field(default=None, alias="qualityStatus")
    quality_reason: str | None = Field(default=None, alias="qualityReason")
    qa_report_path: str | None = Field(default=None, alias="qaReportPath")
    release_manifest_path: str | None = Field(default=None, alias="releaseManifestPath")
    git_branch: str | None = Field(default=None, alias="gitBranch")
    git_commit: str | None = Field(default=None, alias="gitCommit")
    response_verification: ResponseVerification


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
        kernel: KernelService | None = None,
    ) -> None:
        self.router = router
        self.coordinator = coordinator
        self.store = store
        self.settings = settings
        self.provisioner = provisioner
        self.event_publisher = event_publisher
        self.document_service = document_service
        self.kernel = kernel or KernelService(
            router=router, coordinator=coordinator, store=store, settings=settings,
            provisioner=provisioner, event_publisher=event_publisher,
            document_service=document_service,
        )

    def route(
        self, text: str, workspace: str | None = None, *, requested_capability: str | None = None,
    ) -> AssistantRouteResult:
        envelope = self.kernel.route(
            AssistantRequest(raw_text=text, context={"workspace": workspace},
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
                "profile_version": "claimlatch-v0.2.0",
                "subject_id": envelope.execution_id,
            })
        )
        quality_status = output.get("qualityStatus")
        completed_locally = quality_status == "PASS" and response_verification.decision == "PASS"
        status = "completed" if completed_locally else output.get("status", "blocked")
        message = output.get("message", "요청을 완료하지 못했어.")
        if completed_locally:
            message = "로컬 프로젝트가 생성되고 QA/ClaimLatch 검증을 통과했어. 외부 플러그인은 선택적으로 연결할 수 있어."
        elif status == "completed":
            status = "blocked"
            message = (
                response_verification.reason
                if response_verification.decision != "PASS"
                else "완료 검증 증거가 없어."
            )
        return AssistantRouteResult(
            status=status,
            selection=CapabilitySelection.model_validate(output["selection"]),
            message=message,
            project_id=output.get("projectId"),
            project_profile=output.get("projectProfile"),
            missing_connectors=output.get("missingConnectors", []),
            execution_plan_path=output.get("executionPlanPath"),
            planning_session_id=output.get("planningSessionId"),
            planning_handoff_id=output.get("planningHandoffId"),
            quality_status=quality_status,
            quality_reason=output.get("qualityReason"),
            qa_report_path=output.get("qaReportPath"),
            release_manifest_path=output.get("releaseManifestPath"),
            git_branch=output.get("gitBranch"),
            git_commit=output.get("gitCommit"),
            response_verification=response_verification,
        )

    def get_project_profile(self, project_id: str) -> ProjectProfile:
        return self.store.get_project_profile(project_id)

