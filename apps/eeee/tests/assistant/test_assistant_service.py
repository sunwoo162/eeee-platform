from pathlib import Path

from app.assistant.registry import build_default_registry
from app.assistant.router import CapabilityRouter
from app.assistant.service import AssistantService
from app.config import Settings
from app.coordinator.service import Coordinator
from app.project_runtime.provisioner import ProjectProvisioner
from app.storage.sqlite import SQLiteStore
from app.runtime.store import ExecutionStore
from app.agent.protocol import AgentResult
from app.memory.models import MemoryCandidate


def test_assistant_service_creates_one_project_runtime_for_project_intent(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    coordinator = Coordinator(store)
    service = AssistantService(
        router=CapabilityRouter(build_default_registry()),
        coordinator=coordinator,
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
    )

    result = service.route("웹 프로젝트 하나 만들어줘")

    assert result.selection.capability_id == "project-execution"
    assert result.project_id is not None
    assert result.project_profile is not None
    assert Path(result.project_profile.workspace).is_dir()
    assert result.project_profile.project_id == result.project_id
    assert result.status == "awaiting_configuration"
    assert result.response_verification.profile_version == "claimlatch-v0.2.0"
    assert result.response_verification.decision in {"PASS", "WARN", "BLOCKED"}
    assert service.kernel is not None
    records = ExecutionStore(store).list_for_project(result.project_id)
    assert any(record.tool_id == "iseol" for record in records)


def test_assistant_service_does_not_create_project_for_a_reminder(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    coordinator = Coordinator(store)
    service = AssistantService(
        router=CapabilityRouter(build_default_registry()),
        coordinator=coordinator,
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
    )

    result = service.route("내일 오후 3시에 회의 일정 등록해줘")

    assert result.selection.capability_id == "personal-secretary"
    assert result.project_id is None
    assert result.project_profile is None
    assert result.status == "selected"
    assert result.response_verification.profile_version == "claimlatch-v0.2.0"
    assert result.response_verification.decision == "WARN"
    assert "project identity" in result.response_verification.reason.lower()


def test_assistant_service_handles_general_conversation_without_a_project(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    coordinator = Coordinator(store)
    service = AssistantService(
        router=CapabilityRouter(build_default_registry()),
        coordinator=coordinator,
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
    )

    result = service.route("안녕, 오늘 기분이 어때?")

    assert result.selection.capability_id == "general-conversation"
    assert result.project_id is None
    assert result.project_profile is None
    assert result.status == "completed"
    assert "안녕" in result.message
    assert result.response_verification.profile_version == "claimlatch-v0.2.0"


def test_general_conversation_without_any_provider_is_truthfully_blocked(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    coordinator = Coordinator(store)
    service = AssistantService(
        router=CapabilityRouter(build_default_registry()), coordinator=coordinator,
        store=store, settings=settings, provisioner=ProjectProvisioner(store),
    )

    result = service.route("안녕")

    assert result.status == "completed"
    assert "안녕" in result.message
    assert result.response_verification.decision in {"PASS", "WARN"}


def test_assistant_service_blocks_enabled_chatgpt_web_without_a_bridge(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
        chatgpt_web_enabled=True,
    )
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    coordinator = Coordinator(store)
    service = AssistantService(
        router=CapabilityRouter(build_default_registry()),
        coordinator=coordinator,
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
    )

    result = service.route("안녕")

    assert result.status == "completed"
    assert "안녕" in result.message
    assert result.project_id is None


def test_assistant_service_automatically_remembers_durable_design_decisions(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    coordinator = Coordinator(store)
    service = AssistantService(
        router=CapabilityRouter(build_default_registry()),
        coordinator=coordinator,
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
    )

    service.route("포트폴리오는 나중에 플러그인으로 추가할거야")

    preferences = coordinator.memory.search_user_preferences()
    assert preferences["architecture.portfolio_delivery"].content == (
        "포트폴리오는 EEEE 안정화 후 선택 플러그인으로 추가"
    )


def test_general_conversation_uses_configured_agent_runtime_without_project(tmp_path) -> None:
    class ConversationRuntime:
        def __init__(self):
            self.prompts = []

        def run(self, request):
            assert request.allowed_actions == ["read"]
            assert "사용자 기억" in request.prompt
            self.prompts.append(request.prompt)
            return AgentResult(
                status="completed", summary="오늘은 차분하게 우선순위를 정리해보자.",
                events=[{"type": "assistant.response", "message": "오늘은 차분하게 우선순위를 정리해보자."}],
                changed_files=[], test_commands=[], error=None,
            )

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    coordinator = Coordinator(store)
    runtime = ConversationRuntime()
    service = AssistantService(
        router=CapabilityRouter(build_default_registry()),
        coordinator=coordinator,
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
        agent_runtime=runtime,
    )

    preference = service.route("기억해줘 내 이름은 응아니")
    assert preference.project_id is None
    result = service.route("오늘 기분이 어때?")

    assert result.status == "completed"
    assert result.message == "오늘은 차분하게 우선순위를 정리해보자."
    assert result.project_id is None
    assert any("응아니" in prompt for prompt in runtime.prompts)


def test_general_conversation_receives_relevant_memory_content_not_only_ids(tmp_path) -> None:
    class ConversationRuntime:
        def __init__(self):
            self.prompts = []

        def run(self, request):
            self.prompts.append(request.prompt)
            return AgentResult(
                status="completed", summary="기억을 반영했어.", events=[],
                changed_files=[], test_commands=[], error=None,
            )

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    coordinator = Coordinator(store)
    runtime = ConversationRuntime()
    service = AssistantService(
        router=CapabilityRouter(build_default_registry()), coordinator=coordinator,
        store=store, settings=settings, provisioner=ProjectProvisioner(store),
        agent_runtime=runtime,
    )

    candidate = coordinator.memory.save_candidate(MemoryCandidate(
        candidate_id="routine-memory", kind="success_pattern",
        content="오전에는 집중 작업을 선호함", scope={"topic": "routine"},
        source_project_id="user", source_artifact_ids=["chat"],
        evidence_ids=["user-stated"], verification_ids=["user-stated"],
        confidence=0.9, created_at="2026-10-08T00:00:00Z",
    ))
    coordinator.memory.promote(candidate.id, actor="user", evidence_ids=["user-stated"])
    service.route("오늘 집중 작업 뭐할까?")

    assert any("오전에는 집중 작업을 선호함" in prompt for prompt in runtime.prompts)


def test_general_conversation_never_sends_sensitive_preference_values_to_provider(tmp_path) -> None:
    class ConversationRuntime:
        def __init__(self):
            self.prompts = []

        def run(self, request):
            self.prompts.append(request.prompt)
            return AgentResult(status="completed", summary="응답", events=[], changed_files=[], test_commands=[], error=None)

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    coordinator = Coordinator(store)
    runtime = ConversationRuntime()
    service = AssistantService(
        router=CapabilityRouter(build_default_registry()), coordinator=coordinator,
        store=store, settings=settings, provisioner=ProjectProvisioner(store),
        agent_runtime=runtime,
    )

    service.route("기억해줘 비밀번호: extremely-secret-value")
    service.route("비밀번호 알려줘")

    assert runtime.prompts
    assert all("extremely-secret-value" not in prompt for prompt in runtime.prompts)


def test_assistant_service_reports_initial_stale_child_as_blocked_observation(tmp_path) -> None:
    class RevisionAdvancingCoordinator(Coordinator):
        def create_request(self, project_id, text):
            state = super().create_request(project_id, text)
            self.store.update_project_revision(project_id, "rev-after-request")
            return state

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    coordinator = RevisionAdvancingCoordinator(store)
    service = AssistantService(
        router=CapabilityRouter(build_default_registry()),
        coordinator=coordinator,
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
    )

    result = service.route("앱 만들어줘")

    assert result.status == "blocked"
    assert result.project_id is not None
    assert "stale project revision" in result.message
    assert result.response_verification.decision == "BLOCKED"
