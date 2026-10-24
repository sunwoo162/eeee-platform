import asyncio
import json
import logging
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.api.service import ApiFlowService
from app.assistant.models import CapabilitySelection
from app.assistant.growth import GrowthFeedbackError, GrowthService
from app.capabilities.status import canonical_plugin_status
from app.assistant.service import AssistantRouteResult, AssistantService
from app.assistant.background import JobTransitionError
from app.conversations.store import ConversationStore
from app.coordinator.service import Coordinator
from app.domain.errors import ApprovalError
from app.design.references import DesignService, ReferencePack
from app.design.visual_verify import VisualReport
from app.integrations.contracts import ProjectBriefV1, ProjectOutcomeReportV1
from app.integrations.contracts import GithubReviewResultV1
from app.memory.models import GrowthFeedback, MemoryRecord, MemoryStatus
from app.mobile.bridge import MobileBridge, MobileBridgeError
from app.plugins.host import PluginHost
from app.plugins.models import PluginHealth, PluginManifest
from app.plugins.api_models import (
    PluginCatalogView,
    PluginConnectPayload as PlatformPluginConnectPayload,
    PluginHealthView,
    PluginOAuthStartPayload,
)
from app.plugins.oauth import OAuthBroker, OAuthCancelled, OAuthError, OAuthProviderConfig, OAuthStateMismatch
from app.plugins.platform import PluginPlatformService
from app.project_runtime.documents import ProjectDocumentService
from app.project_runtime.evidence import ProjectEvidenceService
from app.project_runtime.models import ProjectDocumentSyncResult, ProjectEvidenceIngestionResult, ProjectProfile
from app.project_view.models import ProjectMapEvents, ProjectMapSnapshot
from app.activity.models import ActivityPage
from app.project_view.service import ProjectViewService
from app.runtime.store import StaleProjectRevision
from app.storage.sqlite import SQLiteStore
from app.trust.gate import TrustGate
from app.domain.models import (
    CandidateScore,
    Decision,
    PetViewModel,
    RequestBrief,
    Run,
)
from app.workflow.planner import WorkPlan, build_work_plan


logger = logging.getLogger(__name__)


def build_project_view_router(service: ProjectViewService) -> APIRouter:
    router = APIRouter(prefix="/api/projects")

    @router.get("/{project_id}/map", response_model=ProjectMapSnapshot)
    def project_map(
        project_id: str, request: Request,
        revision: str | None = Query(default=None, min_length=1),
    ):
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return service.get_snapshot(project_id, revision, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StaleProjectRevision as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/{project_id}/map/events", response_model=ProjectMapEvents)
    def project_map_events(
        project_id: str, request: Request, cursor: int = Query(default=0, ge=0),
        revision: str | None = Query(default=None, min_length=1),
    ):
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return service.get_events(project_id, cursor=cursor, revision=revision, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StaleProjectRevision as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/{project_id}/activity", response_model=ActivityPage)
    def project_activity(
        project_id: str, request: Request, cursor: int = Query(default=0, ge=0),
        revision: str | None = Query(default=None, min_length=1),
    ):
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return service.get_activity(project_id, cursor=cursor, revision=revision, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StaleProjectRevision as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/{project_id}/quality")
    def project_quality(
        project_id: str, request: Request,
        revision: str | None = Query(default=None, min_length=1),
    ):
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return service.get_quality(project_id, revision, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StaleProjectRevision as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/{project_id}/execution-plan")
    def project_execution_plan(
        project_id: str, request: Request,
        revision: str | None = Query(default=None, min_length=1),
    ):
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return service.get_execution_plan(project_id, revision, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StaleProjectRevision as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router


def _normalise_run_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class RequestPayload(BaseModel):
    text: str = Field(min_length=1)
    workspace: str | None = None
    conversation_id: str = Field(default="desktop-default", alias="conversationId")


class ApprovalPayload(BaseModel):
    selected: list[str] = Field(min_length=1)


class RequestResponse(BaseModel):
    request_id: str
    brief: RequestBrief
    run_id: str


class RequestSnapshotResponse(BaseModel):
    request_id: str
    project_id: str
    brief: RequestBrief
    workspace: str
    candidates: list[CandidateScore] = Field(default_factory=list)
    decision: Decision | None = None
    decision_events: list[dict[str, object]] = Field(default_factory=list)
    runs: list[Run] = Field(default_factory=list)
    work_plan: WorkPlan


class ResearchResponse(BaseModel):
    candidates: list[CandidateScore]
    work_plan: WorkPlan


class ApprovalResponse(BaseModel):
    decision: Decision
    run_id: str
    decision_events: list[dict[str, object]] = Field(default_factory=list)


class MemoryPromotionPayload(BaseModel):
    actor: str = Field(min_length=1)
    evidence_ids: list[str] = Field(alias="evidenceIds", min_length=1)

    model_config = {"populate_by_name": True}


class MemoryRevokePayload(BaseModel):
    reason: str = Field(min_length=1)


class MemoryDeletePayload(BaseModel):
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class MemoryDeleteResponse(BaseModel):
    deleted: bool
    memory_id: str = Field(alias="memoryId")


class MemoryCreatePayload(BaseModel):
    content: str = Field(min_length=1)
    source_message_id: str = Field(alias="sourceMessageId", min_length=1)
    actor: str = Field(min_length=1)
    kind: str = "agent_routing_hint"
    scope: dict[str, object] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class MemoryFeedbackPayload(BaseModel):
    client_feedback_id: str = Field(alias="clientFeedbackId", min_length=1, max_length=200)
    conversation_id: str = Field(alias="conversationId", min_length=1, max_length=160)
    message_id: str = Field(alias="messageId", min_length=1, max_length=200)
    request_id: str | None = Field(default=None, alias="requestId", max_length=200)
    rating: Literal["positive", "negative"]
    correction: str | None = Field(default=None, max_length=2_000)
    remember: bool = False
    actor: str = Field(default="user", min_length=1, max_length=120)

    model_config = {"populate_by_name": True}


class MemoryFeedbackResponse(BaseModel):
    feedback_id: str = Field(alias="feedbackId")
    feedback: GrowthFeedback
    memory: MemoryRecord | None = None

    model_config = {"populate_by_name": True}


class UserPreferencePayload(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=2_000)
    scope: dict[str, object] = Field(default_factory=dict)


class MemoryEditPayload(BaseModel):
    content: str = Field(min_length=1)
    actor: str = Field(min_length=1)


class DesignReferencePayload(BaseModel):
    urls: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    target_type: str = Field(min_length=1)


class DesignReferenceResponse(BaseModel):
    id: str
    pack: ReferencePack
    tokens: dict[str, object]


class DesignVerifyPayload(BaseModel):
    url: str = Field(min_length=1)
    baseline: str = Field(min_length=1)


class DesignVerifyResponse(BaseModel):
    id: str
    report: VisualReport


class AssistantRequestPayload(BaseModel):
    text: str = Field(min_length=1)
    workspace: str | None = None
    conversation_id: str = Field(default="desktop-default", alias="conversationId", min_length=1, max_length=160)
    approved: bool = False
    approval_request_id: str | None = Field(default=None, alias="approvalRequestId", min_length=1, max_length=160)
    request_id: str | None = Field(default=None, alias="requestId", min_length=1, max_length=200)

    model_config = {"populate_by_name": True}


class AssistantRouteResponse(AssistantRouteResult):
    selection: CapabilitySelection


class MobilePairPayload(BaseModel):
    pairing_code: str = Field(alias="pairingCode", min_length=6, max_length=6)
    device_name: str = Field(alias="deviceName", min_length=1, max_length=120)

    model_config = {"populate_by_name": True}


class PluginDiscoverPayload(BaseModel):
    source: str = Field(min_length=1)


class LocalPluginConnectPayload(BaseModel):
    approved: bool = False


class PluginInvokePayload(BaseModel):
    action: str = Field(min_length=1)
    input: dict[str, object] = Field(default_factory=dict)
    approved: bool = False
    approval_request_id: str | None = Field(default=None, alias="approvalRequestId", min_length=1, max_length=160)

    model_config = {"populate_by_name": True}


def _plugin_registration_payload(registration: object) -> dict[str, object]:
    return {
        "pluginId": registration.plugin_id,
        "manifestVersion": registration.manifest_version,
        "manifest": registration.manifest,
        "status": registration.status,
        "capabilityStatus": canonical_plugin_status(registration.status),
        "createdAt": registration.created_at,
        "updatedAt": registration.updated_at,
    }


def _plugin_user_id(request: Request, header: str | None) -> str:
    _require_local_desktop(request)
    user_id = (header or "local-user").casefold()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,120}", user_id):
        raise HTTPException(status_code=400, detail="Plugin user scope is invalid")
    return user_id


def build_plugin_router(
    host: PluginHost,
    platform: PluginPlatformService | None = None,
    *,
    oauth_broker: OAuthBroker | None = None,
    oauth_configs: Mapping[str, OAuthProviderConfig] | None = None,
) -> APIRouter:
    """Expose local lifecycle and optional browser-based provider connections."""

    router = APIRouter(prefix="/api/plugins")

    @router.get("")
    def list_plugins() -> list[dict[str, object]]:
        return [_plugin_registration_payload(item) for item in host.list()]

    @router.get("/catalog", response_model=list[PluginCatalogView])
    def plugin_catalog(
        request: Request,
        user_id: str | None = Header(default=None, alias="X-EEEE-User-Id"),
    ) -> list[PluginCatalogView]:
        if platform is None:
            return []
        principal = _plugin_user_id(request, user_id)
        views = []
        for entry in platform.catalog():
            status = platform.status(entry.id, principal)
            setup_status, setup_message = platform.setup_diagnostic(
                entry.id, oauth_configured=entry.id in (oauth_configs or {})
            )
            if setup_status in {"provider_configuration_required", "connector_unavailable"}:
                if status == "not_installed":
                    # Installation is local and must remain available before the
                    # operator configures the provider connector.
                    next_action = "install"
                elif status == "connected":
                    status = "disabled"
                    next_action = "configure"
                else:
                    next_action = "configure"
            else:
                next_action = {
                    "not_installed": "install",
                    "available": "connect",
                    "awaiting_authentication": "connect",
                    "installed": "configure",
                    "connecting": "wait",
                    "connected": "open",
                    "failed": "reconnect",
                    "paused": "resume",
                    "disabled": "configure",
                }.get(status, "connect")
            views.append(PluginCatalogView(
                id=entry.id, name=entry.name, version=entry.version,
                description=entry.description, authMode=entry.auth_mode,
                permissions=entry.permissions, credentialFields=entry.credential_fields,
                permissionDetails=entry.permission_details,
                approvedPermissions=_platform_permissions(platform, entry.id, principal),
                installSource=entry.install_source,
                defaultInstalled=entry.default_installed, status=status,
                setupStatus=setup_status, setupMessage=setup_message,
                nextAction=next_action,
            ))
        return views

    @router.post("/{plugin_id}/install")
    def install_plugin(plugin_id: str, request: Request) -> object:
        _require_local_desktop(request)
        if platform is None:
            raise HTTPException(status_code=503, detail="Plugin platform is unavailable")
        try:
            return platform.install(plugin_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.delete("/{plugin_id}/install", status_code=204)
    def uninstall_plugin(plugin_id: str, request: Request) -> Response:
        _require_local_desktop(request)
        if platform is None:
            raise HTTPException(status_code=503, detail="Plugin platform is unavailable")
        try:
            platform.uninstall(plugin_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(status_code=204)

    @router.get("/{plugin_id}/launch")
    def launch_plugin(
        plugin_id: str,
        request: Request,
        user_id: str | None = Header(default=None, alias="X-EEEE-User-Id"),
    ) -> dict[str, object]:
        if platform is None:
            raise HTTPException(status_code=503, detail="Plugin platform is unavailable")
        _plugin_user_id(request, user_id)
        try:
            return platform.launch_info(plugin_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/{plugin_id}/oauth/start")
    def start_plugin_oauth(
        plugin_id: str,
        request: Request,
        payload: PluginOAuthStartPayload,
        user_id: str | None = Header(default=None, alias="X-EEEE-User-Id"),
    ) -> dict[str, object]:
        if platform is None or oauth_broker is None or oauth_configs is None:
            raise HTTPException(status_code=503, detail="OAuth plugin connection is unavailable")
        config = oauth_configs.get(plugin_id)
        if config is None:
            raise HTTPException(status_code=503, detail="OAuth configuration is unavailable for this plugin")
        principal = _plugin_user_id(request, user_id)
        try:
            if platform.status(plugin_id, principal) == "not_installed":
                raise HTTPException(status_code=409, detail="Plugin must be installed before connecting")
            platform.begin_oauth(
                principal, plugin_id, set(payload.approved_permissions), payload.account_label
            )
            callback = str(request.url_for("plugin_oauth_callback", plugin_id=plugin_id))
            authorization = oauth_broker.start(
                user_id=principal,
                plugin_id=plugin_id,
                config=config,
                redirect_uri=callback,
                approved_permissions=set(payload.approved_permissions),
                account_label=payload.account_label,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "pluginId": plugin_id,
            "authorizationUrl": authorization.authorization_url,
            "state": authorization.state,
            "expiresAt": authorization.expires_at,
        }

    @router.get("/{plugin_id}/oauth/callback", name="plugin_oauth_callback")
    def complete_plugin_oauth(
        plugin_id: str,
        state: str,
        request: Request,
        code: str | None = None,
        error: str | None = None,
        error_description: str | None = None,
    ) -> HTMLResponse:
        del request, error_description
        if platform is None or oauth_broker is None:
            raise HTTPException(status_code=503, detail="OAuth plugin connection is unavailable")
        def mark_connection_failed(error_code: str, user_id: str | None = None) -> None:
            owner = user_id or oauth_broker.owner(state, plugin_id=plugin_id)
            if owner is not None:
                platform.fail_oauth(owner, plugin_id, error_code)
        try:
            completion = oauth_broker.complete(
                user_id=None, plugin_id=plugin_id, state=state, code=code, error=error
            )
            connected = platform.connect(
                completion.user_id,
                plugin_id,
                set(completion.approved_permissions),
                completion.credential,
                completion.account_label,
            )
            if connected.status != "connected":
                mark_connection_failed("oauth_connection_failed", completion.user_id)
                oauth_broker.mark_failed(state, plugin_id, "oauth_connection_failed")
                return _oauth_callback_page(
                    "연결 실패", "플러그인 제공자와 연결하지 못했습니다. 다시 시도해 주세요.", status_code=409
                )
            return _oauth_callback_page(
                "연결 완료",
                "플러그인 계정 연결이 완료됐습니다. 이 창을 닫아도 됩니다.",
            )
        except OAuthCancelled:
            mark_connection_failed("oauth_cancelled")
            return _oauth_callback_page(
                "연결 취소",
                "계정 연결을 취소했습니다. 이 창을 닫아도 됩니다.",
            )
        except OAuthStateMismatch as exc:
            mark_connection_failed("oauth_state_invalid")
            return _oauth_callback_page(
                "연결 확인 실패", "OAuth 요청이 만료됐거나 유효하지 않습니다.", status_code=400
            )
        except OAuthError as exc:
            logger.warning("OAuth completion failed for %s: %s", plugin_id, exc)
            mark_connection_failed("oauth_provider_error")
            oauth_broker.mark_failed(state, plugin_id)
            return _oauth_callback_page(
                "연결 실패", "제공자 인증을 완료하지 못했습니다. 다시 시도해 주세요.", status_code=400
            )
        except PermissionError as exc:
            mark_connection_failed("permission_denied")
            oauth_broker.mark_failed(state, plugin_id, "permission_denied")
            return _oauth_callback_page(
                "권한 부족", "선택한 권한으로 연결할 수 없습니다.", status_code=403
            )
        except (KeyError, RuntimeError) as exc:
            mark_connection_failed("oauth_connection_failed")
            oauth_broker.mark_failed(state, plugin_id)
            return _oauth_callback_page(
                "연결 실패", "플러그인 연결을 완료하지 못했습니다.", status_code=409
            )

    @router.get("/{plugin_id}/oauth/status")
    def plugin_oauth_status(
        plugin_id: str,
        state: str = Query(min_length=1, max_length=256),
        request: Request = None,
    ) -> dict[str, str | None]:
        if oauth_broker is None:
            raise HTTPException(status_code=503, detail="OAuth plugin connection is unavailable")
        if request is not None:
            _require_local_desktop(request)
        return oauth_broker.status(state, plugin_id=plugin_id)

    @router.get("/{plugin_id}/connection")
    def plugin_connection(
        plugin_id: str,
        request: Request,
        user_id: str | None = Header(default=None, alias="X-EEEE-User-Id"),
    ) -> dict[str, object]:
        if platform is None:
            raise HTTPException(status_code=503, detail="Plugin platform is unavailable")
        principal = _plugin_user_id(request, user_id)
        try:
            return platform.get_connection(principal, plugin_id).model_dump(by_alias=True)
        except KeyError:
            try:
                return {"pluginId": plugin_id, "status": platform.status(plugin_id, principal)}
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{plugin_id}/pause")
    def pause_platform_plugin(
        plugin_id: str,
        request: Request,
        user_id: str | None = Header(default=None, alias="X-EEEE-User-Id"),
    ) -> object:
        if platform is not None and plugin_id in {item.id for item in platform.catalog()}:
            try:
                return platform.pause(_plugin_user_id(request, user_id), plugin_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _plugin_registration_payload(host.pause(plugin_id))

    @router.post("/discover", response_model=PluginManifest)
    def discover_plugin(payload: PluginDiscoverPayload) -> PluginManifest:
        try:
            return host.discover(payload.source)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/{plugin_id}/register")
    def register_plugin(plugin_id: str, manifest: PluginManifest) -> dict[str, object]:
        if manifest.id != plugin_id:
            raise HTTPException(status_code=409, detail="Plugin route ID does not match manifest ID")
        try:
            return _plugin_registration_payload(host.register(manifest))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/{plugin_id}/connect")
    def connect_plugin(
        plugin_id: str,
        request: Request,
        payload: LocalPluginConnectPayload | PlatformPluginConnectPayload,
        user_id: str | None = Header(default=None, alias="X-EEEE-User-Id"),
    ) -> object:
        if platform is not None and plugin_id in {item.id for item in platform.catalog()}:
            if not isinstance(payload, PlatformPluginConnectPayload):
                raise HTTPException(status_code=422, detail="Plugin credentials and approvedPermissions are required")
            try:
                return platform.connect(
                    _plugin_user_id(request, user_id), plugin_id,
                    set(payload.approved_permissions), payload.plain_credential(), payload.account_label,
                )
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            except (KeyError, RuntimeError) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            assert isinstance(payload, LocalPluginConnectPayload)
            return _plugin_registration_payload(host.connect(plugin_id, payload.approved))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KeyError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/{plugin_id}/health", response_model=PluginHealth)
    def plugin_health(
        plugin_id: str,
        request: Request,
        user_id: str | None = Header(default=None, alias="X-EEEE-User-Id"),
    ) -> object:
        if platform is not None and plugin_id in {item.id for item in platform.catalog()}:
            try:
                health = platform.health(_plugin_user_id(request, user_id), plugin_id)
                return PluginHealthView(pluginId=plugin_id, **health.model_dump())
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            return host.health(plugin_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{plugin_id}/invoke")
    def invoke_plugin(
        plugin_id: str,
        payload: PluginInvokePayload,
        request: Request,
        user_id: str | None = Header(default=None, alias="X-EEEE-User-Id"),
    ):
        if platform is not None and plugin_id in {item.id for item in platform.catalog()}:
            principal = _plugin_user_id(request, user_id)
            result = platform.invoke(
                principal,
                f"plugin:{plugin_id}:{payload.action}",
                {
                    **payload.input,
                    "approved": payload.approved,
                    **({"approvalRequestId": payload.approval_request_id} if payload.approval_request_id else {}),
                },
            )
            return result.model_dump(mode="json", by_alias=True)
        try:
            return host.invoke(plugin_id, payload.action, payload.input)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{plugin_id}/disconnect")
    def disconnect_plugin(
        plugin_id: str,
        request: Request,
        user_id: str | None = Header(default=None, alias="X-EEEE-User-Id"),
    ) -> object:
        if platform is not None and plugin_id in {item.id for item in platform.catalog()}:
            try:
                platform.disconnect(_plugin_user_id(request, user_id), plugin_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {"pluginId": plugin_id, "status": "awaiting_authentication"}
        try:
            return _plugin_registration_payload(host.disconnect(plugin_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{plugin_id}/pause")
    def pause_plugin(plugin_id: str) -> dict[str, object]:
        try:
            return _plugin_registration_payload(host.pause(plugin_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/{plugin_id}/resume")
    def resume_plugin(
        plugin_id: str,
        request: Request,
        user_id: str | None = Header(default=None, alias="X-EEEE-User-Id"),
    ) -> object:
        if platform is not None and plugin_id in {item.id for item in platform.catalog()}:
            try:
                return platform.resume(_plugin_user_id(request, user_id), plugin_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            return _plugin_registration_payload(host.resume(plugin_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.delete("/{plugin_id}", status_code=204)
    def remove_plugin(plugin_id: str) -> Response:
        try:
            host.remove(plugin_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(status_code=204)

    return router


def _oauth_callback_page(title: str, message: str, *, status_code: int = 200) -> HTMLResponse:
    """Return a small browser-safe callback page without exposing OAuth data."""
    from html import escape

    body = (
        "<!doctype html><html lang='ko'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>EEEE OAuth</title>"
        "<style>body{font-family:system-ui,sans-serif;background:#171820;color:#f7f7fb;"
        "display:grid;place-items:center;min-height:100vh;margin:0}main{max-width:34rem;"
        "padding:2rem;text-align:center}h1{font-size:1.4rem}p{color:#c8cbe0}</style>"
        f"<main><h1>{escape(title)}</h1><p>{escape(message)}</p>"
        "<p>이 창은 닫아도 됩니다.</p></main></html>"
    )
    return HTMLResponse(content=body, status_code=status_code)


def build_router(coordinator: Coordinator) -> APIRouter:
    router = APIRouter()

    @router.post("/projects/{project_id}/requests", response_model=PetViewModel)
    def create_request(
        project_id: str, payload: RequestPayload, request: Request
    ) -> PetViewModel:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return coordinator.create_request(project_id, payload.text, user_id=user_id)

    @router.get("/projects/{project_id}/state", response_model=PetViewModel)
    def get_state(project_id: str, request: Request) -> PetViewModel:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return coordinator.get_state(project_id, user_id=user_id)

    @router.post(
        "/projects/{project_id}/decisions/{request_id}/approve",
        response_model=PetViewModel,
    )
    def approve_selection(
        project_id: str, request_id: str, payload: ApprovalPayload, request: Request
    ) -> PetViewModel:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return coordinator.approve_selection(
            project_id, request_id, payload.selected, user_id=user_id
        )

    @router.post(
        "/projects/{project_id}/tasks/{task_id}/advance",
        response_model=PetViewModel,
    )
    def advance_task(project_id: str, task_id: str, request: Request) -> PetViewModel:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return coordinator.advance_task(project_id, task_id, user_id=user_id)

    @router.post(
        "/projects/{project_id}/tasks/{task_id}/run",
        response_model=PetViewModel,
    )
    def run_task(project_id: str, task_id: str, request: Request) -> PetViewModel:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return coordinator.run_until_checkpoint(project_id, task_id, user_id=user_id)

    @router.post(
        "/projects/{project_id}/tasks/{task_id}/retry",
        response_model=PetViewModel,
    )
    def retry_task(project_id: str, task_id: str, request: Request) -> PetViewModel:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return coordinator.retry_task(project_id, task_id, user_id=user_id)

    @router.get("/projects/{project_id}/reports/{report_id}")
    def get_report(project_id: str, report_id: str, request: Request) -> dict[str, object]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        coordinator.store.get_project(project_id, user_id=user_id)
        report = coordinator.store.get_report(report_id)
        if report.project_id != project_id:
            raise KeyError(f"Report not found: {report_id}")
        return report.model_dump(mode="json")

    return router


def build_assistant_router(
    service: AssistantService,
    documents: ProjectDocumentService | None = None,
    *,
    conversation_store: ConversationStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/assistant/route", response_model=AssistantRouteResponse)
    def route_assistant_request(
        payload: AssistantRequestPayload, request: Request
    ) -> AssistantRouteResponse:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return AssistantRouteResponse.model_validate(
                service.route(
                    payload.text,
                    payload.workspace,
                    conversation_id=payload.conversation_id,
                    approved=payload.approved,
                    approval_request_id=payload.approval_request_id,
                    request_id=payload.request_id,
                    user_id=user_id,
                ).model_dump()
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/assistant/conversations")
    def list_assistant_conversations(
        request: Request,
        query: str = Query(default="", max_length=500),
        limit: int = Query(default=50, ge=1, le=100),
        before_updated_at: str | None = Query(default=None, alias="beforeUpdatedAt", max_length=80),
        before_conversation_id: str | None = Query(
            default=None, alias="beforeConversationId", max_length=200
        ),
    ) -> list[dict[str, object]]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            if conversation_store is not None:
                return conversation_store.list_transcript_summaries(
                    user_id=user_id,
                    query=query,
                    limit=limit,
                    before_updated_at=before_updated_at,
                    before_conversation_id=before_conversation_id,
                )
            if before_updated_at is not None or before_conversation_id is not None:
                raise ValueError("conversation pagination requires the canonical store")
            return service.coordinator.memory.list_conversations(
                query=query, limit=limit, user_id=user_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/assistant/conversations/{conversation_id}")
    def get_assistant_conversation(
        conversation_id: str,
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        before_id: int | None = Query(default=None, alias="beforeId", ge=1),
    ) -> dict[str, object]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            if conversation_store is not None:
                return conversation_store.get_transcript(
                    conversation_id, user_id=user_id, limit=limit, before_sequence=before_id
                )
            return service.coordinator.memory.get_conversation(
                conversation_id, limit=limit, before_id=before_id, user_id=user_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/projects/{project_id}/profile", response_model=ProjectProfile)
    def get_project_profile(project_id: str, request: Request) -> ProjectProfile:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return service.get_project_profile(project_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/assistant/jobs/{job_id}")
    def get_assistant_job(job_id: str, request: Request) -> dict[str, object]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return service.get_background_job(job_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/assistant/jobs")
    def list_assistant_jobs(
        request: Request,
        status: str | None = Query(default=None, max_length=40),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, object]]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return service.list_background_jobs(status=status, limit=limit, user_id=user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _job_action(
        action: Callable[..., dict[str, object]], job_id: str, user_id: str,
    ) -> dict[str, object]:
        try:
            return action(job_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except JobTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/assistant/jobs/{job_id}/pause")
    def pause_assistant_job(job_id: str, request: Request) -> dict[str, object]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return _job_action(service.pause_background_job, job_id, user_id)

    @router.post("/assistant/jobs/{job_id}/resume")
    def resume_assistant_job(job_id: str, request: Request) -> dict[str, object]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return _job_action(service.resume_background_job, job_id, user_id)

    @router.post("/assistant/jobs/{job_id}/cancel")
    def cancel_assistant_job(job_id: str, request: Request) -> dict[str, object]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return _job_action(service.cancel_background_job, job_id, user_id)

    @router.post("/assistant/jobs/{job_id}/retry")
    def retry_assistant_job(job_id: str, request: Request) -> dict[str, object]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return _job_action(service.retry_background_job, job_id, user_id)

    @router.post(
        "/projects/{project_id}/documents/sync",
        response_model=ProjectDocumentSyncResult,
    )
    def sync_project_document(project_id: str, request: Request) -> ProjectDocumentSyncResult:
        if documents is None:
            raise HTTPException(status_code=503, detail="Project document service is unavailable")
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            profile = service.get_project_profile(project_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return documents.sync(profile, user_id=user_id)

    return router


def build_mobile_router(
    bridge: MobileBridge,
    assistant: AssistantService,
    snapshot_provider: Callable[[str | None, str], dict[str, object]],
    *,
    conversation_store: ConversationStore | None = None,
) -> APIRouter:
    """Expose the Desktop-owned remote-control contract for the Mobile client."""

    router = APIRouter(prefix="/api")
    canonical_conversations = conversation_store or getattr(assistant, "conversation_store", None)

    @router.post("/bridge/pairing/code")
    def issue_pairing_code(request: Request) -> dict[str, str]:
        if request.client is not None and request.client.host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            raise HTTPException(status_code=403, detail="Pairing codes can only be issued from Desktop")
        try:
            return bridge.issue_pairing_code(
                user_id=_plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
            )
        except MobileBridgeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/mobile/pair")
    def pair_mobile(payload: MobilePairPayload) -> dict[str, str]:
        try:
            return bridge.pair(payload.pairing_code, payload.device_name)
        except MobileBridgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/mobile/state")
    def mobile_state(
        project_id: str | None = Query(default=None, alias="projectId"),
        bridge_token: str | None = Header(default=None, alias="X-Gleave-Bridge-Token"),
    ) -> dict[str, object]:
        device = _authorize_mobile(bridge, bridge_token)
        return snapshot_provider(project_id, device["userId"])

    @router.get("/mobile/assistant/conversations")
    def list_mobile_assistant_conversations(
        query: str = Query(default="", max_length=500),
        limit: int = Query(default=50, ge=1, le=100),
        before_updated_at: str | None = Query(default=None, alias="beforeUpdatedAt", max_length=80),
        before_conversation_id: str | None = Query(
            default=None, alias="beforeConversationId", max_length=200
        ),
        bridge_token: str | None = Header(default=None, alias="X-Gleave-Bridge-Token"),
    ) -> list[dict[str, object]]:
        device = _authorize_mobile(bridge, bridge_token)
        if canonical_conversations is None:
            raise HTTPException(status_code=503, detail="Canonical conversation store is unavailable")
        try:
            return canonical_conversations.list_transcript_summaries(
                query=query,
                limit=limit,
                before_updated_at=before_updated_at,
                before_conversation_id=before_conversation_id,
                user_id=device["userId"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/mobile/assistant/conversations/{conversation_id}/messages")
    def get_mobile_assistant_messages(
        conversation_id: str,
        limit: int = Query(default=100, ge=1, le=500),
        before_id: int | None = Query(default=None, alias="beforeId", ge=1),
        bridge_token: str | None = Header(default=None, alias="X-Gleave-Bridge-Token"),
    ) -> dict[str, object]:
        device = _authorize_mobile(bridge, bridge_token)
        if canonical_conversations is None:
            raise HTTPException(status_code=503, detail="Canonical conversation store is unavailable")
        try:
            return canonical_conversations.get_transcript(
                conversation_id, limit=limit, before_sequence=before_id,
                user_id=device["userId"],
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/mobile/assistant/route", response_model=AssistantRouteResponse)
    def mobile_assistant_route(
        payload: AssistantRequestPayload,
        bridge_token: str | None = Header(default=None, alias="X-Gleave-Bridge-Token"),
    ) -> AssistantRouteResponse:
        device = _authorize_mobile(bridge, bridge_token)
        try:
            result = assistant.route(
                payload.text,
                payload.workspace,
                conversation_id=payload.conversation_id,
                approved=payload.approved,
                approval_request_id=payload.approval_request_id,
                request_id=payload.request_id,
                user_id=device["userId"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        bridge.publish(
            f"assistant.route.{result.status}",
            {
                "deviceId": device["deviceId"],
                "capabilityId": result.selection.capability_id,
                "status": result.status,
                "projectId": result.project_id,
                "conversationId": payload.conversation_id,
                "requestId": result.request_id,
                "jobId": result.job_id,
            },
        )
        return AssistantRouteResponse.model_validate(result.model_dump())

    @router.get("/mobile/events")
    def mobile_events(
        cursor: int = Query(default=0, ge=0),
        bridge_token: str | None = Header(default=None, alias="X-Gleave-Bridge-Token"),
    ) -> dict[str, object]:
        device = _authorize_mobile(bridge, bridge_token)
        return bridge.events_after(cursor, user_id=device["userId"])

    @router.get("/mobile/events/stream")
    async def mobile_event_stream(
        request: Request,
        cursor: int = Query(default=0, ge=0),
        bridge_token: str | None = Header(default=None, alias="X-Gleave-Bridge-Token"),
    ) -> StreamingResponse:
        device = _authorize_mobile(bridge, bridge_token)

        async def generate() -> object:
            current = cursor
            deadline = asyncio.get_running_loop().time() + 25
            while asyncio.get_running_loop().time() < deadline:
                if await request.is_disconnected():
                    break
                batch = bridge.events_after(current, user_id=device["userId"])
                events = batch["events"]
                if events:
                    for event in events:
                        current = max(current, int(event["cursor"]))
                        yield (
                            f"id: {event['cursor']}\n"
                            f"event: {event['kind']}\n"
                            f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        )
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(generate(), media_type="text/event-stream")

    return router


def build_desktop_router(
    coordinator: Coordinator,
    store: SQLiteStore,
    bridge: MobileBridge,
    trust_gate: TrustGate,
    assistant_service: AssistantService | None = None,
    plugin_host: PluginHost | None = None,
    plugin_platform: PluginPlatformService | None = None,
) -> APIRouter:
    """Expose the local Desktop control-plane without leaking bridge secrets."""

    router = APIRouter(prefix="/api/desktop")

    def _plugin_execution_payload(
        limit: int = 20, *, user_id: str = "local-user",
    ) -> list[dict[str, object]]:
        if assistant_service is None:
            return []
        executions = assistant_service.kernel.executions.list_plugin_routes(
            limit=limit, user_id=user_id
        )
        items: list[dict[str, object]] = []
        for execution in executions:
            output = dict(execution.output or {})
            capability_parts = execution.capability_id.split(":", 2)
            plugin_id = output.get("pluginId")
            if not isinstance(plugin_id, str) and len(capability_parts) >= 2:
                plugin_id = capability_parts[1]
            action = capability_parts[2] if len(capability_parts) >= 3 else execution.capability_id
            plugin_output = output.get("pluginOutput")
            summary = output.get("message")
            if not isinstance(summary, str) or not summary.strip():
                if isinstance(plugin_output, dict) and plugin_output.get("sent") is True:
                    summary = "전송 완료"
                else:
                    summary = "플러그인 실행 결과를 확인해줘."
            items.append({
                "executionId": execution.execution_id,
                "pluginExecutionId": output.get("pluginExecutionId"),
                "pluginId": plugin_id,
                "action": action,
                "status": execution.status.value,
                "approvalState": execution.approval_state.value,
                "summary": summary,
                "startedAt": execution.started_at.isoformat(),
                "completedAt": execution.completed_at.isoformat() if execution.completed_at else None,
            })
        return items

    @router.get("/plugin-executions")
    def desktop_plugin_executions(
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, object]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return {"items": _plugin_execution_payload(limit, user_id=user_id)}

    @router.get("/state")
    def desktop_state(
        request: Request,
        project_id: str | None = Query(default=None, alias="projectId"),
    ) -> dict[str, object]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        events = _desktop_events(bridge, 0, user_id=user_id)["events"]
        snapshot: dict[str, object] = {
            "status": "ok",
            "transport": "desktop-local",
            "claimLatch": trust_gate.health_payload(),
            "mobileBridge": bridge.status(),
            "projectId": project_id,
            "projectProfile": None,
            "projectState": None,
            "events": events[-20:],
            "latestEventCursor": int(events[-1]["cursor"]) if events else 0,
            "pluginExecutions": _plugin_execution_payload(user_id=user_id),
        }
        active_memories = coordinator.memory.list_records(
            status=MemoryStatus.ACTIVE, limit=500, user_id=user_id
        )
        candidate_memories = coordinator.memory.list_records(
            status=MemoryStatus.CANDIDATE, limit=500, user_id=user_id
        )
        jobs = (
            assistant_service.list_background_jobs(limit=20, user_id=user_id)
            if assistant_service is not None else []
        )
        plugins = []
        if plugin_host is not None:
            plugins = [
                {
                    "pluginId": registration.plugin_id,
                    "version": registration.manifest_version,
                    "status": registration.status,
                    "updatedAt": registration.updated_at,
                }
                for registration in plugin_host.list()
            ]
        if plugin_platform is not None:
            for entry in plugin_platform.catalog():
                status = plugin_platform.status(entry.id, user_id)
                plugins.append({
                    "pluginId": entry.id,
                    "name": entry.name,
                    "version": entry.version,
                    "description": entry.description,
                    "authMode": entry.auth_mode,
                    "permissions": entry.permissions,
                    "credentialFields": [field.model_dump(by_alias=True) for field in entry.credential_fields],
                    "permissionDetails": [detail.model_dump(by_alias=True) for detail in entry.permission_details],
                    "installSource": entry.install_source,
                    "status": status,
                    "nextAction": {
                        "not_installed": "install",
                        "available": "connect",
                        "awaiting_authentication": "connect",
                        "installed": "configure",
                        "connected": "open",
                        "failed": "reconnect",
                        "paused": "resume",
                        "disabled": "configure",
                    }.get(status, "connect"),
                    "approvedPermissions": _platform_permissions(
                        plugin_platform, entry.id, user_id
                    ),
                })
        snapshot["controlCenter"] = {
            "sections": [
                "conversation", "activeWork", "projects", "plugins", "memory", "settings"
            ],
            "jobs": jobs,
            "memory": {
                "activeCount": len(active_memories),
                "candidateCount": len(candidate_memories),
            },
            "plugins": plugins,
            "pluginExecutions": snapshot["pluginExecutions"],
            "verification": {"claimLatch": trust_gate.health_payload()},
        }
        if project_id is not None:
            try:
                snapshot["projectProfile"] = store.get_project_profile(
                    project_id, user_id=user_id
                ).model_dump(mode="json", by_alias=True)
                snapshot["projectState"] = coordinator.get_state(
                    project_id, user_id=user_id
                ).model_dump(mode="json")
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            project_state = snapshot["projectState"]
            snapshot["state"] = project_state["state"]
            snapshot["message"] = project_state["message"]
            snapshot["controlCenter"]["verification"]["releaseGate"] = {
                "status": "not_evaluated",
                "reason": "Release evidence is recorded in the project revision manifest",
                "projectId": project_id,
                "projectRevision": snapshot["projectProfile"]["projectRevision"],
            }
        return snapshot

    @router.get("/events")
    def desktop_events(
        request: Request,
        cursor: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return _desktop_events(bridge, cursor, user_id=user_id)

    @router.post("/pairing/code")
    def desktop_pairing_code(request: Request) -> dict[str, str]:
        _require_local_desktop(request)
        try:
            return bridge.issue_pairing_code(
                user_id=_plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
            )
        except MobileBridgeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return router


def _require_local_desktop(request: Request) -> None:
    if request.client is not None and request.client.host not in {
        "127.0.0.1",
        "::1",
        "localhost",
        "testclient",
    }:
        raise HTTPException(status_code=403, detail="Desktop control is local-only")


def _platform_permissions(
    platform: PluginPlatformService, plugin_id: str, user_id: str = "local-user"
) -> list[str]:
    try:
        return platform.get_connection(user_id, plugin_id).approved_permissions
    except KeyError:
        return []


def _desktop_events(
    bridge: MobileBridge, cursor: int, *, user_id: str | None = None
) -> dict[str, object]:
    batch = bridge.events_after(cursor)
    events = [
        event for event in batch["events"] if _desktop_event_visible(event, user_id)
    ]
    return {
        "cursor": batch["cursor"],
        "hasGap": batch["hasGap"],
        "oldestCursor": batch["oldestCursor"],
        "events": [_redact_desktop_event(event) for event in events],
    }


def _desktop_event_visible(event: object, user_id: str | None) -> bool:
    if user_id is None or not isinstance(event, dict):
        return True
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return True
    scoped_user_id = payload.get("userId")
    return not isinstance(scoped_user_id, str) or scoped_user_id == user_id


def _redact_desktop_event(event: object) -> dict[str, object]:
    if not isinstance(event, dict):
        return {"cursor": 0, "kind": "unknown", "payload": {}}
    return {
        "cursor": event.get("cursor", 0),
        "kind": event.get("kind", "unknown"),
        "createdAt": event.get("createdAt"),
        "payload": _redact_desktop_value(event.get("payload", {})),
    }


def _redact_desktop_value(value: object) -> object:
    sensitive = {
        "accesstoken",
        "apikey",
        "authorization",
        "pairingcode",
        "password",
        "prompt",
        "rawtext",
        "token",
    }
    if isinstance(value, dict):
        return {
            key: _redact_desktop_value(item)
            for key, item in value.items()
            if str(key).replace("_", "").lower() not in sensitive
        }
    if isinstance(value, list):
        return [_redact_desktop_value(item) for item in value]
    return value


def _authorize_mobile(bridge: MobileBridge, token: str | None) -> dict[str, str]:
    try:
        return bridge.authorize(token)
    except MobileBridgeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def build_api_router(
    flow: ApiFlowService,
    evidence: ProjectEvidenceService | None = None,
    *,
    iseol_bridge_token: str | None = None,
    conversation_store: ConversationStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/requests", response_model=RequestResponse)
    def create_api_request(payload: RequestPayload, request: Request) -> RequestResponse:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            request_id, brief, run_id = flow.create_request(
                payload.text,
                payload.workspace,
                conversation_id=payload.conversation_id,
                user_id=user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RequestResponse(request_id=request_id, brief=brief, run_id=run_id)

    @router.get("/requests/{request_id}", response_model=RequestSnapshotResponse)
    def get_api_request(request_id: str, request: Request) -> RequestSnapshotResponse:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            snapshot = flow.get_request_snapshot(request_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RequestSnapshotResponse(
            **snapshot.model_dump(mode="python"),
            work_plan=build_work_plan(snapshot.brief, snapshot.candidates),
        )

    @router.get("/requests/{request_id}/project-brief", response_model=ProjectBriefV1)
    def get_project_brief(request_id: str, request: Request) -> ProjectBriefV1:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            project_id, _workspace, _project = flow._project_for_request(
                request_id, user_id=user_id
            )
            return flow.coordinator.build_project_brief(
                project_id, request_id, user_id=user_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post(
        "/projects/{project_id}/outcomes",
        response_model=list[MemoryRecord],
    )
    def ingest_project_outcome(
        project_id: str, payload: ProjectOutcomeReportV1, request: Request
    ) -> list[MemoryRecord]:
        if payload.project_id != project_id:
            raise HTTPException(status_code=409, detail="Outcome project does not match the route")
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return flow.coordinator.record_project_outcome(payload, user_id=user_id)

    @router.post(
        "/projects/{project_id}/evidence/github-review",
        response_model=ProjectEvidenceIngestionResult,
    )
    def ingest_github_review_evidence(
        project_id: str,
        payload: GithubReviewResultV1,
        request: Request,
        bridge_token: str | None = Header(default=None, alias="X-Gleave-Bridge-Token"),
    ) -> ProjectEvidenceIngestionResult:
        if iseol_bridge_token is not None and bridge_token != iseol_bridge_token:
            raise HTTPException(status_code=401, detail="ISEOL bridge token is invalid")
        if payload.project_id != project_id:
            raise HTTPException(status_code=409, detail="Evidence project does not match the route")
        if evidence is None:
            raise HTTPException(status_code=503, detail="Project evidence service is unavailable")
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return evidence.ingest_github_review(payload, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ApprovalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/memory", response_model=list[MemoryRecord])
    def search_memory(
        request: Request,
        query: str = Query(default="", max_length=500),
        status: MemoryStatus | None = Query(default=None),
        source_project_id: str | None = Query(default=None, alias="sourceProjectId", max_length=160),
        project_type: str | None = Query(default=None, alias="projectType", max_length=120),
        technology: str | None = Query(default=None, max_length=120),
        feature: str | None = Query(default=None, max_length=120),
        risk: str | None = Query(default=None, max_length=120),
        workstream: str | None = Query(default=None, max_length=120),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[MemoryRecord]:
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        scope = {
            key: value
            for key, value in {
                "projectType": project_type,
                "technology": technology,
                "feature": feature,
                "risk": risk,
                "workstream": workstream,
            }.items()
            if value is not None
        }
        if status is not None or source_project_id is not None:
            return flow.coordinator.memory.list_records(
                status=status,
                source_project_id=source_project_id,
                query=query,
                scope=scope or None,
                limit=limit,
                user_id=user_id,
            )
        return flow.coordinator.memory.search(
            query, scope=scope or None, limit=limit, user_id=user_id
        )

    @router.get("/memory/{memory_id}", response_model=MemoryRecord)
    def get_memory(memory_id: str, request: Request) -> MemoryRecord:
        try:
            user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
            return flow.coordinator.memory.get(memory_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/memory/user-preference", response_model=MemoryRecord)
    def save_user_preference(payload: UserPreferencePayload, request: Request) -> MemoryRecord:
        try:
            user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
            return flow.coordinator.remember_user_preference(
                payload.key, payload.value, scope=payload.scope, user_id=user_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post(
        "/memory/feedback",
        response_model=MemoryFeedbackResponse,
        status_code=201,
        responses={200: {"model": MemoryFeedbackResponse}},
    )
    def record_memory_feedback(
        payload: MemoryFeedbackPayload, request: Request
    ) -> JSONResponse:
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        already_exists = False
        try:
            flow.coordinator.memory.get_feedback(payload.client_feedback_id, user_id=user_id)
            already_exists = True
        except KeyError:
            pass
        try:
            growth = GrowthService(flow.coordinator.memory, conversation_store)
            feedback = growth.record_feedback(
                client_feedback_id=payload.client_feedback_id,
                conversation_id=payload.conversation_id,
                request_id=payload.request_id,
                message_id=payload.message_id,
                rating=payload.rating,
                correction=payload.correction,
                remember=payload.remember,
                actor=payload.actor,
                user_id=user_id,
            )
            memory = growth.memory_for_feedback(feedback)
        except GrowthFeedbackError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response = MemoryFeedbackResponse(
            feedback_id=feedback.id,
            feedback=feedback,
            memory=memory,
        )
        return JSONResponse(
            status_code=200 if already_exists else 201,
            content=response.model_dump(mode="json", by_alias=True),
        )

    @router.post("/memory", response_model=MemoryRecord, status_code=201)
    def create_explicit_memory(
        payload: MemoryCreatePayload, request: Request
    ) -> MemoryRecord:
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return flow.coordinator.memory.save_explicit_memory(
            payload.content,
            source_message_id=payload.source_message_id,
            actor=payload.actor,
            kind=payload.kind,
            scope=payload.scope,
            user_id=user_id,
        )

    @router.patch("/memory/{memory_id}", response_model=MemoryRecord)
    def edit_explicit_memory(
        memory_id: str, payload: MemoryEditPayload, request: Request
    ) -> MemoryRecord:
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return flow.coordinator.memory.edit(
            memory_id, payload.content, actor=payload.actor, user_id=user_id
        )

    @router.post("/memory/{memory_id}/promote", response_model=MemoryRecord)
    def promote_memory(
        memory_id: str, payload: MemoryPromotionPayload, request: Request
    ) -> MemoryRecord:
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        return flow.coordinator.promote_memory(
            memory_id,
            actor=payload.actor,
            evidence_ids=payload.evidence_ids,
            user_id=user_id,
        )

    @router.post("/memory/{memory_id}/revoke", response_model=MemoryRecord)
    def revoke_memory(
        memory_id: str, payload: MemoryRevokePayload, request: Request
    ) -> MemoryRecord:
        try:
            user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
            return flow.coordinator.memory.revoke(
                memory_id, reason=payload.reason, user_id=user_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/memory/{memory_id}/delete", response_model=MemoryDeleteResponse)
    def delete_memory(
        memory_id: str, payload: MemoryDeletePayload, request: Request
    ) -> MemoryDeleteResponse:
        try:
            user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
            deleted = flow.coordinator.memory.delete(
                memory_id,
                actor=payload.actor,
                reason=payload.reason,
                user_id=user_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return MemoryDeleteResponse(deleted=True, memoryId=deleted.id)

    @router.post("/requests/{request_id}/research", response_model=ResearchResponse)
    def research_api_request(request_id: str, request: Request) -> ResearchResponse:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            candidates, work_plan = flow.research(request_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return ResearchResponse(candidates=candidates, work_plan=work_plan)

    @router.post("/requests/{request_id}/approve", response_model=ApprovalResponse)
    def approve_api_request(
        request_id: str, payload: ApprovalPayload, request: Request
    ) -> ApprovalResponse:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            decision, run_id, decision_events = flow.approve(
                request_id, payload.selected, user_id=user_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ApprovalResponse(
            decision=decision,
            run_id=run_id,
            decision_events=decision_events,
        )

    @router.post("/runs/{run_id}/execute", response_model=Run)
    def execute_api_run(run_id: str, request: Request) -> Run:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return flow.execute(run_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/runs", response_model=list[Run])
    def list_api_runs(
        request: Request,
        response: Response,
        request_id: str | None = None,
        status: Literal["created", "running", "completed", "failed", "unavailable"] | None = None,
        search: str | None = Query(default=None, max_length=200),
        created_after: datetime | None = Query(default=None),
        created_before: datetime | None = Query(default=None),
        sort: Literal["newest", "oldest"] = "newest",
        limit: int | None = Query(default=None, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> list[Run]:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        runs, total = flow.list_runs_with_count(
            request_id,
            status=status,
            search=search,
            created_after=_normalise_run_timestamp(created_after),
            created_before=_normalise_run_timestamp(created_before),
            sort=sort,
            limit=None if limit is None else limit + 1,
            offset=offset,
            user_id=user_id,
        )
        response.headers["X-Total-Count"] = str(total)
        if limit is None:
            return runs
        has_more = len(runs) > limit
        response.headers["X-Has-More"] = str(has_more).lower()
        return runs[:limit]

    @router.post("/runs/{run_id}/retry", response_model=Run)
    def retry_api_run(run_id: str, request: Request) -> Run:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return flow.retry(run_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/runs/{run_id}", response_model=Run)
    def get_api_run(run_id: str, request: Request) -> Run:
        _require_local_desktop(request)
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            return flow.get_run(run_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def build_design_router(design: DesignService) -> APIRouter:
    router = APIRouter(prefix="/api/design")

    @router.post("/references", response_model=DesignReferenceResponse)
    def create_design_references(
        payload: DesignReferencePayload, request: Request,
    ) -> DesignReferenceResponse:
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            pack_id, pack, tokens = design.create(
                payload.urls, payload.keywords, payload.target_type, user_id=user_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return DesignReferenceResponse(id=pack_id, pack=pack, tokens=tokens)

    @router.get("/references/{pack_id}", response_model=DesignReferenceResponse)
    def get_design_references(pack_id: str, request: Request) -> DesignReferenceResponse:
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            pack, tokens = design.get(pack_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return DesignReferenceResponse(id=pack_id, pack=pack, tokens=tokens)

    @router.post("/verify")
    def verify_design(payload: DesignVerifyPayload, request: Request) -> DesignVerifyResponse:
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        verification_id, report = design.verify(
            payload.url, payload.baseline, user_id=user_id
        )
        return DesignVerifyResponse(id=verification_id, report=report)

    @router.get("/verify/{verification_id}", response_model=DesignVerifyResponse)
    def get_design_verification(
        verification_id: str, request: Request
    ) -> DesignVerifyResponse:
        user_id = _plugin_user_id(request, request.headers.get("X-EEEE-User-Id"))
        try:
            _url, _baseline, report = design.get_verification(
                verification_id, user_id=user_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return DesignVerifyResponse(id=verification_id, report=report)

    return router
