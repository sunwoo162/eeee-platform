from contextlib import asynccontextmanager
from pathlib import Path
from collections.abc import Mapping

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agent.local_runtime import LocalAgentRuntime, LocalConversationRuntime, OllamaBackend
from app.agent.local_model_discovery import discover_fast_local_model, discover_local_model
from app.agent.ollama_runtime import OllamaRuntime
from app.agent.personal_llm_runtime import PersonalLlmRuntime
from app.agent.conversation_runtime import ConversationProviderAgentRuntime
from app.agent.protocol import AgentRuntime
from app.activity.store import ActivityLedger
from app.agent.lazy_runtime import LazyAgentRuntime
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
from app.api.conversation_routes import build_conversation_router
from app.assistant.registry import build_default_registry
from app.assistant.router import CapabilityRouter
from app.assistant.background import BackgroundExecutionSupervisor
from app.assistant.service import AssistantService
from app.capabilities.registry import build_core_capability_manager
from app.config import Settings
from app.conversations.context import ConversationContextBuilder
from app.conversations.models import MessageRole, MessageStatus
from app.conversations.providers import (
    BuiltinConversationProvider,
    ChatGptWebConversationProvider,
    PersonalLlmConversationProvider,
    build_conversation_provider,
)
from app.conversations.multimodel import ProviderHub
from app.conversations.service import ConversationProvider, ConversationService
from app.conversations.store import ConversationStore
from app.chat_scopes.store import WorkspaceStore
from app.chat_scopes.routes import build_workspace_router
from app.codex_integration.routes import build_codex_router
from app.codex_integration.runtime import CodexTaskManager, CodexUnavailable
from app.codex_integration.journal import CodexJournal
from app.contracts import LocalEventBus
from app.core.lifecycle import CoreLifecycle
from app.core.lock import ProcessLock
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
from app.project_runtime.documents import PluginPlatformNotionAdapter, ProjectDocumentService
from app.project_runtime.evidence import ProjectEvidenceService
from app.project_view.service import ProjectViewService
from app.plugins.host import PluginHost
from app.plugins.notion_connector import NotionConnector
from app.plugins.oauth import HttpOAuthTransport, OAuthBroker, OAuthProviderConfig
from app.plugins.platform import PluginPlatformService
from app.plugins.providers import build_provider_connectors, load_provider_configs
from app.storage.sqlite import SQLiteStore
from app.trust.gate import TrustGate
from app.trust.pipeline import TrustPipeline


def create_app(
    settings: Settings | None = None,
    *,
    researcher: GitHubResearcher | None = None,
    agent_runtime: AgentRuntime | None = None,
    conversation_provider: ConversationProvider | None = None,
    notion_client: NotionClient | None = None,
    oauth_broker: OAuthBroker | None = None,
    oauth_configs: Mapping[str, OAuthProviderConfig] | None = None,
) -> FastAPI:
    from app.agent.chatgpt_web_agent_runtime import ChatGptWebAgentRuntime
    from app.agent.chatgpt_web_runtime import ChatGptWebRuntime
    from app.agent.hybrid_runtime import FastLocalConversationRuntime, HybridAssistantRuntime

    app_settings = settings or Settings()
    configured_provider_configs = load_provider_configs(
        app_settings.plugin_provider_config_json,
        gmail_client_id=app_settings.gmail_oauth_client_id,
        gmail_client_secret=app_settings.gmail_oauth_client_secret,
    )
    provider_connectors = build_provider_connectors(configured_provider_configs)
    configured_oauth_configs: dict[str, OAuthProviderConfig] = {
        plugin_id: config.oauth
        for plugin_id, config in configured_provider_configs.items()
    }
    configured_oauth_configs.update(oauth_configs or {})
    application = FastAPI(title=app_settings.app_name)
    store = SQLiteStore(app_settings.data_dir / "state.sqlite3")
    store.init()
    assistant_supervisor = BackgroundExecutionSupervisor(store, max_workers=1)
    ollama_runtime = OllamaRuntime(
        base_url=app_settings.ollama_base_url,
        model=app_settings.ollama_model,
        connect_timeout_seconds=app_settings.ollama_connect_timeout_seconds,
        generation_timeout_seconds=app_settings.ollama_generation_timeout_seconds,
        context_tokens=app_settings.ollama_context_tokens,
    )
    personal_llm_runtime = PersonalLlmRuntime(
        base_url=app_settings.personal_llm_base_url,
        connect_timeout_seconds=app_settings.personal_llm_connect_timeout_seconds,
        generation_timeout_seconds=app_settings.personal_llm_generation_timeout_seconds,
    )
    web_runtime: AgentRuntime | None = None
    if app_settings.chatgpt_web_enabled and app_settings.chatgpt_web_bridge_url:
        web_runtime = ChatGptWebRuntime(
            app_settings.chatgpt_web_bridge_url,
            timeout_seconds=app_settings.chatgpt_web_timeout_seconds,
            profile_path=app_settings.assistant_profile_path,
            conversation_state_path=app_settings.data_dir / "chatgpt-assistant-conversation.json",
        )
    web_runtime_status = web_runtime.status() if web_runtime is not None else None
    provider_selection = None
    selected_conversation_provider = conversation_provider
    if selected_conversation_provider is None:
        provider_selection = build_conversation_provider(
            app_settings.conversation_provider,
            ollama=ollama_runtime,
            web=web_runtime,
            personal_llm=personal_llm_runtime,
            workspace=app_settings.workspace_root,
            context_tokens=app_settings.ollama_context_tokens,
            web_status=web_runtime_status,
            builtin=BuiltinConversationProvider(),
        )
        selected_conversation_provider = provider_selection.provider
    conversation_store = ConversationStore(store)
    workspace_store = WorkspaceStore(store)
    conversation_context = ConversationContextBuilder(
        conversation_store,
        max_context_tokens=app_settings.ollama_context_tokens,
    )
    conversation_context.workspace_store = workspace_store
    conversation_service = ConversationService(
        conversation_store,
        provider=selected_conversation_provider,
        context_builder=conversation_context,
    )
    provider_hub = (
        ProviderHub(selected_conversation_provider)
        if conversation_provider is not None
        else ProviderHub.from_environment(
            selected_conversation_provider,
            personal_llm=PersonalLlmConversationProvider(personal_llm_runtime),
            ollama=ollama_runtime,
            chatgpt_web=(
                ChatGptWebConversationProvider(
                    web_runtime, workspace=app_settings.workspace_root,
                    context_tokens=app_settings.ollama_context_tokens,
                ) if web_runtime is not None else None
            ),
        )
    )
    conversation_service.provider_hub = provider_hub
    core_lifecycle = CoreLifecycle(
        store,
        conversation_service,
        lock=ProcessLock(app_settings.data_dir / "core.lock"),
    )

    @asynccontextmanager
    async def core_lifespan(_application: FastAPI):
        core_lifecycle.start()
        try:
            yield
        finally:
            codex_manager.shutdown()
            core_lifecycle.stop()

    application.router.lifespan_context = core_lifespan
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
    conversation_context.memory_store = coordinator.memory
    activity_ledger = ActivityLedger(store)
    planning_service = PlanningService(store, activity_ledger)
    plugin_platform = PluginPlatformService(
        store,
        plugin_install_root=app_settings.data_dir / "plugins",
        connectors={
            "notion": NotionConnector(
                client_factory=lambda credential: NotionClient(
                    credential["token"],
                    parent_page_id=credential["parentPageId"],
                    base_url=app_settings.notion_api_base,
                    api_version=app_settings.notion_api_version,
                )
            )
        } | provider_connectors,
    )
    configured_oauth_broker = oauth_broker or OAuthBroker(HttpOAuthTransport())
    capability_router = CapabilityRouter(
        build_default_registry(),
        plugin_status_provider=plugin_platform.status,
    )
    capability_manager = build_core_capability_manager()
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
        configured_connector_ids=lambda user_id="local-user": {
            *configured_connectors,
            *plugin_platform.connected_connector_ids(
                user_id, required_permissions={"notion": {"pages.write"}}
            ),
        },
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
    project_documents = ProjectDocumentService(
        store,
        configured_notion or PluginPlatformNotionAdapter(plugin_platform),
        trust_gate,
        mobile_bridge.publish,
    )
    project_evidence = ProjectEvidenceService(store, trust_gate, mobile_bridge.publish)
    application.state.coordinator = coordinator
    application.state.activity_ledger = activity_ledger
    application.state.claim_latch_client = claim_latch_client
    application.state.claim_latch_process = claim_latch_process
    application.state.trust_gate = trust_gate
    application.state.mobile_bridge = mobile_bridge
    application.state.project_documents = project_documents
    application.state.project_evidence = project_evidence
    application.state.ollama_runtime = ollama_runtime
    application.state.personal_llm_runtime = personal_llm_runtime
    application.state.chatgpt_web_runtime = web_runtime
    application.state.conversation_provider_selection = provider_selection
    application.state.conversation_store = conversation_store
    application.state.workspace_store = workspace_store
    def archive_codex_task(task) -> None:
        # After a completed/failed agent run, persist its outcome in the same
        # canonical conversation used by GPT/Claude. Never save hidden
        # provider instructions as if the user typed them.
        conversation_store.get_conversation(task.conversation_id, user_id=task.user_id)
        conversation_store.add_message(
            task.conversation_id, role=MessageRole.USER,
            content=task.display_prompt, status=MessageStatus.COMPLETED,
            client_message_id=f"codex:{task.id}",
        )
        success = task.status == "completed"
        report = task.answer.strip() if success and task.answer.strip() else (
            "Codex 작업 완료. 상세 결과가 기록되지 않았습니다."
            if success else f"Codex 작업 {task.status}: {task.error or '완료되지 않음'}"
        )
        conversation_store.add_message(
            task.conversation_id, role=MessageRole.ASSISTANT,
            content=report[:15000],
            status=MessageStatus.COMPLETED if success else (
                MessageStatus.CANCELLED if task.status == "cancelled" else MessageStatus.FAILED
            ),
            provider="codex", model="app-server",
            error_code=None if success else "codex_task_incomplete",
        )
        task.publish("chatSaved", "Codex 작업 결과를 이 채팅에 저장했습니다.")

    codex_journal = CodexJournal(store)
    codex_manager = CodexTaskManager(on_finished=archive_codex_task, journal=codex_journal)
    try:
        codex_manager.configured_executable()
        provider_hub.available["codex"] = True
    except CodexUnavailable:
        provider_hub.available["codex"] = False
    application.state.codex_manager = codex_manager
    application.state.conversation_service = conversation_service
    application.state.core_lifecycle = core_lifecycle
    application.state.capabilities = capability_manager
    @asynccontextmanager
    async def application_lifespan(_application: FastAPI):
        core_lifecycle.start()
        try:
            yield
        finally:
            core_lifecycle.stop()
            if claim_latch_process is not None:
                claim_latch_process.stop()
            assistant_supervisor.shutdown()

    application.router.lifespan_context = application_lifespan
    # Ollama is an explicit migration/debug lane only. Ordinary conversation
    # uses the selected provider above; project execution remains a separate
    # runtime and must not silently hijack the chat lane.
    ollama_legacy_enabled = app_settings.conversation_provider == "ollama"
    local_model_name = None
    local_conversation_model_name = None
    if ollama_legacy_enabled:
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
    web_agent_runtime = None
    if runtime is None and web_runtime is not None:
        web_agent_runtime = ChatGptWebAgentRuntime(
            web_runtime=web_runtime,
            workspace_root=app_settings.workspace_root,
            timeout_seconds=app_settings.chatgpt_web_agent_timeout_seconds,
        )
        runtime = web_agent_runtime
    if runtime is None:
        runtime = HybridAssistantRuntime(web=None)
    # The ordinary EEEE conversation lane uses the selected conversation
    # provider. Personal LLM, Web GPT, and Ollama remain separate lanes.
    if ollama_legacy_enabled and local_conversation_model_name:
        local_general_runtime = LocalConversationRuntime(
            backend=OllamaBackend(
                model=local_conversation_model_name,
                base_url=app_settings.local_model_base_url,
                timeout=app_settings.local_model_timeout_seconds,
            )
        )
    else:
        local_general_runtime = None
    active_web_runtime = None if ollama_legacy_enabled else web_runtime
    if provider_selection is not None and provider_selection.provider_name == "personal_llm":
        general_runtime: AgentRuntime = ConversationProviderAgentRuntime(
            provider_selection.provider
        )
    else:
        general_runtime = HybridAssistantRuntime(
            local=local_general_runtime,
            web=active_web_runtime,
            builtin=FastLocalConversationRuntime(),
        )
    # Project execution keeps its existing runtime boundary; conversation
    # generation is selected independently above.
    project_agent_runtime = runtime
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
        conversation_store=conversation_store,
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
        conversation_store=conversation_store,
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
        conversation_store=conversation_store,
    )
    application.state.assistant_service = assistant_service
    assistant_service.resume_background_jobs()
    design_service = DesignService(store=store)
    application.state.design_service = design_service
    plugin_host = PluginHost(store, execution_store=kernel.executions)
    kernel.plugin_host = plugin_host
    capability_router.registry.set_dynamic_provider(
        lambda user_id="local-user": [
            *plugin_host.routing_capabilities(),
            *plugin_platform.capabilities(user_id),
        ]
    )
    application.state.plugin_host = plugin_host
    application.state.plugin_platform = plugin_platform
    application.state.oauth_broker = configured_oauth_broker
    application.state.oauth_configs = dict(configured_oauth_configs)

    def mobile_snapshot(project_id: str | None, user_id: str) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "status": "ok",
            "transport": "desktop-bridge",
            "bridge": mobile_bridge.status(),
            "claimLatch": trust_gate.health_payload(),
        }
        if project_id is not None:
            snapshot["projectId"] = project_id
            snapshot["state"] = coordinator.get_state(project_id, user_id=user_id).model_dump(mode="json")
            snapshot["projectProfile"] = store.get_project_profile(
                project_id, user_id=user_id
            ).model_dump(mode="json")
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
    application.include_router(
        build_conversation_router(
            conversation_service,
            ollama=ollama_runtime,
            personal_llm=personal_llm_runtime,
            provider_selection=provider_selection,
            web_configured=web_runtime is not None,
            web_status=getattr(web_runtime_status, "status", None),
            web_status_provider=web_runtime.status if web_runtime is not None else None,
            lifecycle=core_lifecycle,
            capabilities=capability_manager,
            schema_version=1,
        )
    )
    application.include_router(build_workspace_router(workspace_store, conversation_store))
    application.include_router(
        build_codex_router(
            workspace_store, conversation_store, codex_manager,
            workspace_root=app_settings.workspace_root,
        )
    )
    application.include_router(build_project_view_router(project_view))
    application.include_router(
        build_assistant_router(
            assistant_service,
            project_documents,
            conversation_store=conversation_store,
        )
    )
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
            conversation_store=conversation_store,
        )
    )
    application.include_router(build_design_router(design_service))
    application.include_router(
        build_plugin_router(
            plugin_host,
            plugin_platform,
            oauth_broker=configured_oauth_broker,
            oauth_configs=configured_oauth_configs,
        )
    )
    # The React chat frontend is an optional build artifact. Keep the legacy
    # EEEE root UI functional when frontend dependencies are not installed.
    chat_dist = Path(__file__).resolve().parents[3] / "apps" / "desktop" / "chat-ui" / "dist"
    if (chat_dist / "index.html").is_file() and (chat_dist / "assets").is_dir():
        application.mount(
            "/chat/assets",
            StaticFiles(directory=chat_dist / "assets"),
            name="gleave-chat-assets",
        )

        @application.get("/chat", include_in_schema=False)
        @application.get("/chat/", include_in_schema=False)
        def chat_index() -> FileResponse:
            return FileResponse(chat_dist / "index.html")

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


def _build_optional_runtime(settings: Settings):
    if settings.agent_runtime == "openhands":
        return _build_openhands_runtime(settings)
    if settings.iseol_control_plane_url:
        return _build_iseol_runtime(settings)
    return _build_chatgpt_web_runtime(settings)


def _build_openhands_runtime(settings: Settings):
    from app.agent.openhands_runtime import OpenHandsRuntime

    return OpenHandsRuntime(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
    )


def _build_iseol_runtime(settings: Settings):
    from app.agent.iseol_runtime import IseolProjectRuntime, IseolProjectRuntimeConfig

    return IseolProjectRuntime(IseolProjectRuntimeConfig(
        base_url=settings.iseol_control_plane_url or "",
        token=settings.iseol_control_plane_token,
        timeout_seconds=settings.chatgpt_web_timeout_seconds,
    ))


def _build_chatgpt_web_runtime(settings: Settings):
    from app.agent.chatgpt_web_runtime import (
        ChatGptWebRuntime,
        default_chatgpt_web_runtime_config,
    )

    repository_root = Path(__file__).resolve().parents[3]
    bridge_script = settings.iseol_bridge_script
    if not bridge_script.is_absolute():
        bridge_script = repository_root / bridge_script
    return ChatGptWebRuntime(
        config=default_chatgpt_web_runtime_config(
            bridge_script=bridge_script,
            node_executable=settings.iseol_node_executable,
            working_directory=bridge_script.parent.parent,
            timeout_seconds=settings.chatgpt_web_timeout_seconds,
        )
    )


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    uvicorn.run("app.main:create_app", factory=True, host=host, port=port)


if __name__ == "__main__":
    run()
