from pathlib import Path

from app.assistant.registry import build_default_registry
from app.assistant.router import CapabilityRouter
from app.assistant.service import AssistantService
from app.config import Settings
from app.coordinator.service import Coordinator
from app.project_runtime.provisioner import ProjectProvisioner
from app.storage.sqlite import SQLiteStore
from app.runtime.store import ExecutionStore


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
    assert "EEEE" in result.message
    assert result.response_verification.profile_version == "claimlatch-v0.2.0"


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
