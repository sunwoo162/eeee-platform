import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.service import ApiFlowService
from app.assistant.models import CapabilitySelection
from app.assistant.service import AssistantRouteResult, AssistantService
from app.coordinator.service import Coordinator
from app.domain.errors import ApprovalError
from app.design.references import DesignService, ReferencePack
from app.design.visual_verify import VisualReport
from app.integrations.contracts import ProjectBriefV1, ProjectOutcomeReportV1
from app.integrations.contracts import GithubReviewResultV1
from app.memory.models import MemoryRecord
from app.mobile.bridge import MobileBridge, MobileBridgeError
from app.plugins.host import PluginHost
from app.plugins.models import PluginHealth, PluginManifest
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


def build_project_view_router(service: ProjectViewService) -> APIRouter:
    router = APIRouter(prefix="/api/projects")

    @router.get("/{project_id}/map", response_model=ProjectMapSnapshot)
    def project_map(project_id: str, revision: str | None = Query(default=None, min_length=1)):
        try:
            return service.get_snapshot(project_id, revision)
        except StaleProjectRevision as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/{project_id}/map/events", response_model=ProjectMapEvents)
    def project_map_events(project_id: str, cursor: int = Query(default=0, ge=0),
                           revision: str | None = Query(default=None, min_length=1)):
        try:
            return service.get_events(project_id, cursor=cursor, revision=revision)
        except StaleProjectRevision as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/{project_id}/activity", response_model=ActivityPage)
    def project_activity(project_id: str, cursor: int = Query(default=0, ge=0),
                          revision: str | None = Query(default=None, min_length=1)):
        try:
            return service.get_activity(project_id, cursor=cursor, revision=revision)
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


class UserPreferencePayload(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=2_000)
    scope: dict[str, object] = Field(default_factory=dict)


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


class AssistantRouteResponse(AssistantRouteResult):
    selection: CapabilitySelection


class MobilePairPayload(BaseModel):
    pairing_code: str = Field(alias="pairingCode", min_length=6, max_length=6)
    device_name: str = Field(alias="deviceName", min_length=1, max_length=120)

    model_config = {"populate_by_name": True}


class PluginDiscoverPayload(BaseModel):
    source: str = Field(min_length=1)


class PluginConnectPayload(BaseModel):
    approved: bool = False


class PluginInvokePayload(BaseModel):
    action: str = Field(min_length=1)
    input: dict[str, object] = Field(default_factory=dict)


def _plugin_registration_payload(registration: object) -> dict[str, object]:
    return {
        "pluginId": registration.plugin_id,
        "manifestVersion": registration.manifest_version,
        "manifest": registration.manifest,
        "status": registration.status,
        "createdAt": registration.created_at,
        "updatedAt": registration.updated_at,
    }


def build_plugin_router(host: PluginHost) -> APIRouter:
    """Expose the local plugin lifecycle; no remote plugin registry is involved."""

    router = APIRouter(prefix="/api/plugins")

    @router.get("")
    def list_plugins() -> list[dict[str, object]]:
        return [_plugin_registration_payload(item) for item in host.list()]

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
    def connect_plugin(plugin_id: str, payload: PluginConnectPayload) -> dict[str, object]:
        try:
            return _plugin_registration_payload(host.connect(plugin_id, payload.approved))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KeyError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/{plugin_id}/health", response_model=PluginHealth)
    def plugin_health(plugin_id: str) -> PluginHealth:
        try:
            return host.health(plugin_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{plugin_id}/invoke")
    def invoke_plugin(plugin_id: str, payload: PluginInvokePayload):
        try:
            return host.invoke(plugin_id, payload.action, payload.input)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{plugin_id}/disconnect")
    def disconnect_plugin(plugin_id: str) -> dict[str, object]:
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
    def resume_plugin(plugin_id: str) -> dict[str, object]:
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


def build_router(coordinator: Coordinator) -> APIRouter:
    router = APIRouter()

    @router.post("/projects/{project_id}/requests", response_model=PetViewModel)
    def create_request(project_id: str, payload: RequestPayload) -> PetViewModel:
        return coordinator.create_request(project_id, payload.text)

    @router.get("/projects/{project_id}/state", response_model=PetViewModel)
    def get_state(project_id: str) -> PetViewModel:
        return coordinator.get_state(project_id)

    @router.post(
        "/projects/{project_id}/decisions/{request_id}/approve",
        response_model=PetViewModel,
    )
    def approve_selection(
        project_id: str, request_id: str, payload: ApprovalPayload
    ) -> PetViewModel:
        return coordinator.approve_selection(project_id, request_id, payload.selected)

    @router.post(
        "/projects/{project_id}/tasks/{task_id}/advance",
        response_model=PetViewModel,
    )
    def advance_task(project_id: str, task_id: str) -> PetViewModel:
        return coordinator.advance_task(project_id, task_id)

    @router.post(
        "/projects/{project_id}/tasks/{task_id}/run",
        response_model=PetViewModel,
    )
    def run_task(project_id: str, task_id: str) -> PetViewModel:
        return coordinator.run_until_checkpoint(project_id, task_id)

    @router.post(
        "/projects/{project_id}/tasks/{task_id}/retry",
        response_model=PetViewModel,
    )
    def retry_task(project_id: str, task_id: str) -> PetViewModel:
        return coordinator.retry_task(project_id, task_id)

    @router.get("/projects/{project_id}/reports/{report_id}")
    def get_report(project_id: str, report_id: str) -> dict[str, object]:
        report = coordinator.store.get_report(report_id)
        if report.project_id != project_id:
            raise KeyError(f"Report not found: {report_id}")
        return report.model_dump(mode="json")

    return router


def build_assistant_router(
    service: AssistantService, documents: ProjectDocumentService | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/assistant/route", response_model=AssistantRouteResponse)
    def route_assistant_request(payload: AssistantRequestPayload) -> AssistantRouteResponse:
        try:
            return AssistantRouteResponse.model_validate(
                service.route(payload.text, payload.workspace).model_dump()
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/projects/{project_id}/profile", response_model=ProjectProfile)
    def get_project_profile(project_id: str) -> ProjectProfile:
        return service.get_project_profile(project_id)

    @router.post(
        "/projects/{project_id}/documents/sync",
        response_model=ProjectDocumentSyncResult,
    )
    def sync_project_document(project_id: str) -> ProjectDocumentSyncResult:
        if documents is None:
            raise HTTPException(status_code=503, detail="Project document service is unavailable")
        profile = service.get_project_profile(project_id)
        return documents.sync(profile)

    return router


def build_mobile_router(
    bridge: MobileBridge,
    assistant: AssistantService,
    snapshot_provider: Callable[[str | None], dict[str, object]],
) -> APIRouter:
    """Expose the Desktop-owned remote-control contract for the Mobile client."""

    router = APIRouter(prefix="/api")

    @router.post("/bridge/pairing/code")
    def issue_pairing_code(request: Request) -> dict[str, str]:
        if request.client is not None and request.client.host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            raise HTTPException(status_code=403, detail="Pairing codes can only be issued from Desktop")
        try:
            return bridge.issue_pairing_code()
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
        _authorize_mobile(bridge, bridge_token)
        return snapshot_provider(project_id)

    @router.post("/mobile/assistant/route", response_model=AssistantRouteResponse)
    def mobile_assistant_route(
        payload: AssistantRequestPayload,
        bridge_token: str | None = Header(default=None, alias="X-Gleave-Bridge-Token"),
    ) -> AssistantRouteResponse:
        device = _authorize_mobile(bridge, bridge_token)
        try:
            result = assistant.route(payload.text, payload.workspace)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        bridge.publish(
            "assistant.route.completed",
            {
                "deviceId": device["deviceId"],
                "capabilityId": result.selection.capability_id,
                "status": result.status,
                "projectId": result.project_id,
            },
        )
        return AssistantRouteResponse.model_validate(result.model_dump())

    @router.get("/mobile/events")
    def mobile_events(
        cursor: int = Query(default=0, ge=0),
        bridge_token: str | None = Header(default=None, alias="X-Gleave-Bridge-Token"),
    ) -> dict[str, object]:
        _authorize_mobile(bridge, bridge_token)
        return bridge.events_after(cursor)

    @router.get("/mobile/events/stream")
    async def mobile_event_stream(
        request: Request,
        cursor: int = Query(default=0, ge=0),
        bridge_token: str | None = Header(default=None, alias="X-Gleave-Bridge-Token"),
    ) -> StreamingResponse:
        _authorize_mobile(bridge, bridge_token)

        async def generate() -> object:
            current = cursor
            deadline = asyncio.get_running_loop().time() + 25
            while asyncio.get_running_loop().time() < deadline:
                if await request.is_disconnected():
                    break
                batch = bridge.events_after(current)
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
) -> APIRouter:
    """Expose the local Desktop control-plane without leaking bridge secrets."""

    router = APIRouter(prefix="/api/desktop")

    @router.get("/state")
    def desktop_state(
        request: Request,
        project_id: str | None = Query(default=None, alias="projectId"),
    ) -> dict[str, object]:
        _require_local_desktop(request)
        events = _desktop_events(bridge, 0)["events"]
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
        }
        if project_id is not None:
            snapshot["projectProfile"] = store.get_project_profile(project_id).model_dump(
                mode="json", by_alias=True
            )
            snapshot["projectState"] = coordinator.get_state(project_id).model_dump(
                mode="json"
            )
        return snapshot

    @router.get("/events")
    def desktop_events(
        request: Request,
        cursor: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        _require_local_desktop(request)
        return _desktop_events(bridge, cursor)

    @router.post("/pairing/code")
    def desktop_pairing_code(request: Request) -> dict[str, str]:
        _require_local_desktop(request)
        try:
            return bridge.issue_pairing_code()
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


def _desktop_events(bridge: MobileBridge, cursor: int) -> dict[str, object]:
    batch = bridge.events_after(cursor)
    return {
        "cursor": batch["cursor"],
        "events": [_redact_desktop_event(event) for event in batch["events"]],
    }


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
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/requests", response_model=RequestResponse)
    def create_api_request(payload: RequestPayload) -> RequestResponse:
        try:
            request_id, brief, run_id = flow.create_request(payload.text, payload.workspace)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RequestResponse(request_id=request_id, brief=brief, run_id=run_id)

    @router.get("/requests/{request_id}", response_model=RequestSnapshotResponse)
    def get_api_request(request_id: str) -> RequestSnapshotResponse:
        snapshot = flow.get_request_snapshot(request_id)
        return RequestSnapshotResponse(
            **snapshot.model_dump(mode="python"),
            work_plan=build_work_plan(snapshot.brief, snapshot.candidates),
        )

    @router.get("/requests/{request_id}/project-brief", response_model=ProjectBriefV1)
    def get_project_brief(request_id: str) -> ProjectBriefV1:
        project_id, _workspace = flow.store.get_request_context(request_id)
        return flow.coordinator.build_project_brief(project_id, request_id)

    @router.post(
        "/projects/{project_id}/outcomes",
        response_model=list[MemoryRecord],
    )
    def ingest_project_outcome(
        project_id: str, payload: ProjectOutcomeReportV1
    ) -> list[MemoryRecord]:
        if payload.project_id != project_id:
            raise HTTPException(status_code=409, detail="Outcome project does not match the route")
        return flow.coordinator.record_project_outcome(payload)

    @router.post(
        "/projects/{project_id}/evidence/github-review",
        response_model=ProjectEvidenceIngestionResult,
    )
    def ingest_github_review_evidence(
        project_id: str,
        payload: GithubReviewResultV1,
        bridge_token: str | None = Header(default=None, alias="X-Gleave-Bridge-Token"),
    ) -> ProjectEvidenceIngestionResult:
        if iseol_bridge_token is not None and bridge_token != iseol_bridge_token:
            raise HTTPException(status_code=401, detail="ISEOL bridge token is invalid")
        if payload.project_id != project_id:
            raise HTTPException(status_code=409, detail="Evidence project does not match the route")
        if evidence is None:
            raise HTTPException(status_code=503, detail="Project evidence service is unavailable")
        try:
            return evidence.ingest_github_review(payload)
        except ApprovalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/memory", response_model=list[MemoryRecord])
    def search_memory(
        query: str = Query(default="", max_length=500),
        project_type: str | None = Query(default=None, alias="projectType", max_length=120),
        technology: str | None = Query(default=None, max_length=120),
        feature: str | None = Query(default=None, max_length=120),
        risk: str | None = Query(default=None, max_length=120),
        workstream: str | None = Query(default=None, max_length=120),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[MemoryRecord]:
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
        return flow.coordinator.memory.search(query, scope=scope or None, limit=limit)

    @router.post("/memory/user-preference", response_model=MemoryRecord)
    def save_user_preference(payload: UserPreferencePayload) -> MemoryRecord:
        try:
            return flow.coordinator.remember_user_preference(
                payload.key, payload.value, scope=payload.scope
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/memory/{memory_id}/promote", response_model=MemoryRecord)
    def promote_memory(
        memory_id: str, payload: MemoryPromotionPayload
    ) -> MemoryRecord:
        return flow.coordinator.promote_memory(
            memory_id,
            actor=payload.actor,
            evidence_ids=payload.evidence_ids,
        )

    @router.post("/memory/{memory_id}/revoke", response_model=MemoryRecord)
    def revoke_memory(memory_id: str, payload: MemoryRevokePayload) -> MemoryRecord:
        return flow.coordinator.memory.revoke(memory_id, reason=payload.reason)

    @router.post("/requests/{request_id}/research", response_model=ResearchResponse)
    def research_api_request(request_id: str) -> ResearchResponse:
        try:
            candidates, work_plan = flow.research(request_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return ResearchResponse(candidates=candidates, work_plan=work_plan)

    @router.post("/requests/{request_id}/approve", response_model=ApprovalResponse)
    def approve_api_request(
        request_id: str, payload: ApprovalPayload
    ) -> ApprovalResponse:
        decision, run_id, decision_events = flow.approve(request_id, payload.selected)
        return ApprovalResponse(
            decision=decision,
            run_id=run_id,
            decision_events=decision_events,
        )

    @router.post("/runs/{run_id}/execute", response_model=Run)
    def execute_api_run(run_id: str) -> Run:
        return flow.execute(run_id)

    @router.get("/runs", response_model=list[Run])
    def list_api_runs(
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
        runs, total = flow.list_runs_with_count(
            request_id,
            status=status,
            search=search,
            created_after=_normalise_run_timestamp(created_after),
            created_before=_normalise_run_timestamp(created_before),
            sort=sort,
            limit=None if limit is None else limit + 1,
            offset=offset,
        )
        response.headers["X-Total-Count"] = str(total)
        if limit is None:
            return runs
        has_more = len(runs) > limit
        response.headers["X-Has-More"] = str(has_more).lower()
        return runs[:limit]

    @router.post("/runs/{run_id}/retry", response_model=Run)
    def retry_api_run(run_id: str) -> Run:
        return flow.retry(run_id)

    @router.get("/runs/{run_id}", response_model=Run)
    def get_api_run(run_id: str) -> Run:
        return flow.get_run(run_id)

    return router


def build_design_router(design: DesignService) -> APIRouter:
    router = APIRouter(prefix="/api/design")

    @router.post("/references", response_model=DesignReferenceResponse)
    def create_design_references(
        payload: DesignReferencePayload,
    ) -> DesignReferenceResponse:
        try:
            pack_id, pack, tokens = design.create(
                payload.urls, payload.keywords, payload.target_type
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return DesignReferenceResponse(id=pack_id, pack=pack, tokens=tokens)

    @router.get("/references/{pack_id}", response_model=DesignReferenceResponse)
    def get_design_references(pack_id: str) -> DesignReferenceResponse:
        pack, tokens = design.get(pack_id)
        return DesignReferenceResponse(id=pack_id, pack=pack, tokens=tokens)

    @router.post("/verify")
    def verify_design(payload: DesignVerifyPayload) -> DesignVerifyResponse:
        verification_id, report = design.verify(payload.url, payload.baseline)
        return DesignVerifyResponse(id=verification_id, report=report)

    @router.get("/verify/{verification_id}", response_model=DesignVerifyResponse)
    def get_design_verification(verification_id: str) -> DesignVerifyResponse:
        _url, _baseline, report = design.get_verification(verification_id)
        return DesignVerifyResponse(id=verification_id, report=report)

    return router
