from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agent.local_runtime import LocalAgentRuntime, LocalConversationRuntime, OllamaBackend
from app.agent.local_model_discovery import discover_fast_local_model, discover_local_model
from app.agent.openhands_runtime import OpenHandsRuntime
from app.agent.protocol import AgentRuntime
from app.agent.chatgpt_web_runtime import ChatGptWebRuntime
from app.agent.chatgpt_web_agent_runtime import ChatGptWebAgentRuntime
from app.agent.hybrid_runtime import HybridAssistantRuntime
from app.activity.store import ActivityLedger
from app.api.service import ApiFlowService
from app.api.routes import (
    build_api_router,
    build_assistant_router,
    build_design_router,
    build_desktop_router,
    build_mobile_router,
    build_plugin_router,
    build_project_view_router,
    build_router,
)
from app.assistant.registry import build_default_registry
from app.assistant.router import CapabilityRouter
from app.assistant.background import BackgroundExecutionSupervisor
from app.assistant.service import AssistantService
from app.config import Settings
from app.contracts import LocalEventBus
from app.coordinator.service import Coordinator
from app.design.references import DesignService
from app.domain.errors import ApprovalError
from app.execution.runner import WorkspaceCommandRunner
from app.execution.verifier import WorkspaceVerifier
from app.integrations.claimlatch_client import ClaimLatchClient
from app.integrations.claimlatch_process import ClaimLatchProcessManager
from app.integrations.notion_client import NotionClient
from app.kernel.service import KernelService
from app.mobile.bridge import MobileBridge
from app.oss.github_client import GitHubClient
from app.oss.researcher import GitHubResearcher
from app.project_runtime.provisioner import ProjectProvisioner
from app.project_runtime.iseol_bridge import IseolPlanBridge
from app.planning.service import PlanningService
from app.project_runtime.connectors import build_default_connectors
from app.project_runtime.documents import ProjectDocumentService
from app.project_runtime.evidence import ProjectEvidenceService
from app.project_view.service import ProjectViewService
from app.plugins.host import PluginHost
from app.plugins.notion_connector import NotionConnector
from app.plugins.platform import PluginPlatformService
from app.storage.sqlite import SQLiteStore
from app.trust.gate import TrustGate
from app.trust.pipeline import TrustPipeline


def create_app(
    settings: Settings | None = None,
    *,
    researcher: GitHubResearcher | None = None,
    agent_runtime: AgentRuntime | None = None,
    notion_client: NotionClient | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    application = FastAPI(title=app_settings.app_name)
    store = SQLiteStore(app_settings.data_dir / "state.sqlite3")
    store.init()
    assistant_supervisor = BackgroundExecutionSupervisor(store, max_workers=1)
    mobile_bridge = MobileBridge(
        store.path,
        enabled=app_settings.mobile_bridge_enabled,
        pairing_ttl_seconds=app_settings.mobile_pairing_ttl_seconds,
    )
    mobile_bridge.init()
    configured_researcher = researcher if researcher is not None else (
        GitHubResearcher(GitHubClient(token=app_settings.github_token))
        if app_settings.github_token
        else None
    )
    verifier = None
    if app_settings.execution_mode == "workspace_verify":
        verifier = WorkspaceVerifier(
            WorkspaceCommandRunner(
                app_settings.workspace_root,
                default_timeout_seconds=app_settings.command_timeout_seconds,
                max_output_chars=app_settings.max_command_output_chars,
            )
        )
    coordinator = Coordinator(store, researcher=configured_researcher, verifier=verifier)
    activity_ledger = ActivityLedger(store)
    planning_service = PlanningService(store, activity_ledger)
    plugin_platform = PluginPlatformService(
        store,
        connectors={
            "notion": NotionConnector(
                client_factory=lambda credential: NotionClient(
                    credential["token"],
                    parent_page_id=credential["parentPageId"],
                    base_url=app_settings.notion_api_base,
                    api_version=app_settings.notion_api_version,
                )
            )
        },
    )
    capability_router = CapabilityRouter(
        build_default_registry(),
        plugin_status_provider=plugin_platform.status,
    )
    configured_connectors = {
        connector_id
        for connector_id, configured in {
            "github": bool(app_settings.github_token),
            "notion": bool(app_settings.notion_token and app_settings.notion_parent_page_id),
        }.items()
        if configured
    }
    project_provisioner = ProjectProvisioner(
        store,
        connectors=build_default_connectors(configured=configured_connectors),
        iseol_bridge=IseolPlanBridge(timeout=app_settings.command_timeout_seconds),
    )
    app_settings.workspace_root.mkdir(parents=True, exist_ok=True)
    default_workspace = app_settings.workspace_root / "default"
    default_workspace.mkdir(parents=True, exist_ok=True)
    try:
        store.get_project("default")
    except KeyError:
        coordinator.create_project(
            "default",
            app_settings.app_name,
            str(default_workspace),
        )
    claim_latch_process = None
    claim_latch_adapter_url = app_settings.claim_latch_adapter_url
    if not claim_latch_adapter_url and app_settings.claim_latch_auto_start:
        claim_latch_process = ClaimLatchProcessManager(
            repo_root=Path(__file__).resolve().parents[3],
            port=app_settings.claim_latch_adapter_port,
            llm_model=app_settings.claimlatch_llm_model,
            llm_api_key=app_settings.claimlatch_llm_api_key,
            llm_base_url=app_settings.claimlatch_llm_base_url,
            tavily_api_key=app_settings.tavily_api_key,
        )
        started = claim_latch_process.start()
        claim_latch_adapter_url = started.url if started.started else None
    claim_latch_client = None
    if claim_latch_adapter_url:
        claim_latch_client = ClaimLatchClient(
            claim_latch_adapter_url,
            audit_store=store.claimlatch_audits,
            policy_version=app_settings.claim_latch_policy_version,
            adapter_version=app_settings.claim_latch_adapter_version,
            claim_latch_profile_version=app_settings.claim_latch_profile_version,
            claim_latch_version=app_settings.claim_latch_version,
            current_revision_resolver=_current_project_revision(store),
        )
    trust_gate = TrustGate(
        claim_latch_client,
        mode=app_settings.claim_latch_mode,
        profile_version=app_settings.claim_latch_profile_version,
        engine_version=app_settings.claim_latch_version,
        current_revision_resolver=_current_project_revision(store),
    )
    coordinator.trust_gate = trust_gate
    coordinator.trust_pipeline = TrustPipeline(
        trust_gate, audit_store=store.claimlatch_audits, activity=activity_ledger
    )
    configured_notion = notion_client
    if configured_notion is None and app_settings.notion_token and app_settings.notion_parent_page_id:
        configured_notion = NotionClient(
            app_settings.notion_token,
            parent_page_id=app_settings.notion_parent_page_id,
            base_url=app_settings.notion_api_base,
            api_version=app_settings.notion_api_version,
        )
    project_documents = ProjectDocumentService(store, configured_notion, trust_gate, mobile_bridge.publish)
    project_evidence = ProjectEvidenceService(store, trust_gate, mobile_bridge.publish)
    application.state.coordinator = coordinator
    application.state.activity_ledger = activity_ledger
    application.state.claim_latch_client = claim_latch_client
    application.state.claim_latch_process = claim_latch_process
    application.state.trust_gate = trust_gate
    application.state.mobile_bridge = mobile_bridge
    application.state.project_documents = project_documents
    application.state.project_evidence = project_evidence
    if claim_latch_process is not None:
        @application.on_event("shutdown")
        async def stop_claim_latch_plugin() -> None:
            claim_latch_process.stop()

    @application.on_event("shutdown")
    async def stop_assistant_supervisor() -> None:
        assistant_supervisor.shutdown()
    local_model_name = app_settings.local_model or discover_local_model(
        app_settings.local_model_base_url, timeout_seconds=0.2
    )
    local_conversation_model_name = (
        app_settings.local_conversation_model
        or discover_fast_local_model(app_settings.local_model_base_url, timeout_seconds=0.2)
        or local_model_name
    )
    runtime = agent_runtime
    if runtime is None and local_model_name:
        runtime = LocalAgentRuntime(
            backend=OllamaBackend(
                model=local_model_name,
                base_url=app_settings.local_model_base_url,
                timeout=app_settings.local_model_timeout_seconds,
            ),
            workspace_root=app_settings.workspace_root,
            command_timeout_seconds=app_settings.command_timeout_seconds,
        )
    if runtime is None:
        runtime = OpenHandsRuntime(
            api_key=app_settings.llm_api_key,
            model=app_settings.llm_model,
            base_url=app_settings.llm_base_url,
        )
    web_runtime: AgentRuntime | None = None
    if app_settings.chatgpt_web_enabled and app_settings.chatgpt_web_bridge_url:
        web_runtime = ChatGptWebRuntime(
            app_settings.chatgpt_web_bridge_url,
            timeout_seconds=app_settings.chatgpt_web_timeout_seconds,
            profile_path=app_settings.assistant_profile_path,
            conversation_state_path=app_settings.data_dir / "chatgpt-assistant-conversation.json",
        )
    # The general conversation lane must never inherit the project/ISEOL
    # runtime.  ``agent_runtime`` is the project execution provider and may
    # be ChatGPT Web; reusing it here silently turns a greeting into a slow
    # browser request.  Keep ordinary conversation on the local fast model
    # whenever one is installed, and let HybridAssistantRuntime use Web only
    # for complex/tool requests or as a truthful fallback.
    if local_conversation_model_name:
        local_general_runtime = LocalConversationRuntime(
            backend=OllamaBackend(
                model=local_conversation_model_name,
                base_url=app_settings.local_model_base_url,
                timeout=app_settings.local_model_timeout_seconds,
            )
        )
    else:
        # Do not present the canned emergency lane as a real AI provider. If
        # the local model is absent, the hybrid runtime must either use the
        # explicitly connected Web lane or report the provider as unavailable.
        # This prevents every casual message from becoming the same fake reply.
        local_general_runtime = None
    # Keep the general assistant lane separate from the ISEOL project runtime.
    # Even with no configured provider, use the hybrid facade so the user gets
    # a truthful unavailable response instead of an OpenHands/API-key error.
    general_runtime: AgentRuntime = HybridAssistantRuntime(
        local=local_general_runtime, web=web_runtime
    )
    if agent_runtime is not None:
        project_agent_runtime = agent_runtime
    elif web_runtime is not None:
        project_agent_runtime = ChatGptWebAgentRuntime(
            web_runtime=web_runtime,
            workspace_root=app_settings.workspace_root,
            timeout_seconds=app_settings.chatgpt_web_agent_timeout_seconds,
        )
    else:
        # Do not route an unconfigured installation through OpenHands. That
        # leaks an implementation-specific LLM_API_KEY error after a project
        # job has already been accepted. The local model is intentionally
        # reserved for ordinary conversation; projects belong to the
        # GPT-Web/ISEOL lane and must fail closed when that lane is absent.
        project_agent_runtime = HybridAssistantRuntime(web=web_runtime)
    api_flow = ApiFlowService(
        coordinator,
        store,
        app_settings,
        runtime,
        capability_router=capability_router,
        project_provisioner=project_provisioner,
        trust_gate=trust_gate,
        trust_pipeline=coordinator.trust_pipeline,
        event_publisher=mobile_bridge.publish,
    )
    application.state.api_flow = api_flow
    event_bus = LocalEventBus()
    kernel = KernelService(
        router=capability_router, coordinator=coordinator, store=store,
        settings=app_settings, provisioner=project_provisioner, memory=coordinator.memory,
        trust_gate=trust_gate, event_bus=event_bus, event_publisher=mobile_bridge.publish,
        document_service=project_documents, planning_service=planning_service,
        # Always pass the selected runtime into ISEOL.  A runtime without
        # credentials reports a blocked execution; omitting it would let the
        # project runner skip every specialist and falsely release a scaffold.
        agent_runtime=project_agent_runtime,
        general_runtime=general_runtime,
        chatgpt_web_enabled=app_settings.chatgpt_web_enabled,
        plugin_platform=plugin_platform,
    )
    application.state.kernel = kernel
    application.state.execution_store = kernel.executions
    application.state.assistant_supervisor = assistant_supervisor
    application.state.event_bus = event_bus
    project_view = ProjectViewService(store, activity_ledger)
    application.state.project_view = project_view
    assistant_service = AssistantService(
        router=capability_router,
        coordinator=coordinator,
        store=store,
        settings=app_settings,
        provisioner=project_provisioner,
        event_publisher=mobile_bridge.publish,
        document_service=project_documents,
        kernel=kernel,
        background_supervisor=assistant_supervisor,
    )
    application.state.assistant_service = assistant_service
    assistant_service.resume_background_jobs()
    design_service = DesignService(store=store)
    application.state.design_service = design_service
    plugin_host = PluginHost(store, execution_store=kernel.executions)
    kernel.plugin_host = plugin_host
    capability_router.registry.set_dynamic_provider(
        lambda: [*plugin_host.routing_capabilities(), *plugin_platform.capabilities()]
    )
    application.state.plugin_host = plugin_host
    application.state.plugin_platform = plugin_platform

    def mobile_snapshot(project_id: str | None) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "status": "ok",
            "transport": "desktop-bridge",
            "bridge": mobile_bridge.status(),
            "claimLatch": trust_gate.health_payload(),
        }
        if project_id is not None:
            snapshot["projectId"] = project_id
            snapshot["state"] = coordinator.get_state(project_id).model_dump(mode="json")
            snapshot["projectProfile"] = store.get_project_profile(project_id).model_dump(mode="json")
        return snapshot

    @application.exception_handler(ApprovalError)
    async def handle_approval_error(_request: Request, exc: ApprovalError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.exception_handler(KeyError)
    async def handle_key_error(_request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc).strip("'")})

    @application.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "claimLatch": trust_gate.health_payload()}

    application.include_router(build_router(coordinator))
    application.include_router(build_project_view_router(project_view))
    application.include_router(build_assistant_router(assistant_service, project_documents))
    application.include_router(build_mobile_router(mobile_bridge, assistant_service, mobile_snapshot))
    application.include_router(
        build_desktop_router(
            coordinator,
            store,
            mobile_bridge,
            trust_gate,
            assistant_service=assistant_service,
            plugin_host=plugin_host,
            plugin_platform=plugin_platform,
        )
    )
    application.include_router(
        build_api_router(
            api_flow,
            project_evidence,
            iseol_bridge_token=app_settings.iseol_bridge_token,
        )
    )
    application.include_router(build_design_router(design_service))
    application.include_router(build_plugin_router(plugin_host, plugin_platform))
    static_dir = Path(__file__).parent / "static"
    application.mount("/static", StaticFiles(directory=static_dir), name="static")

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return application


def _current_project_revision(store: SQLiteStore):
    def resolve(project_id: str) -> str | None:
        try:
            return store.get_project(project_id).revision
        except KeyError:
            return None

    return resolve


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    uvicorn.run("app.main:create_app", factory=True, host=host, port=port)


if __name__ == "__main__":
    run()
