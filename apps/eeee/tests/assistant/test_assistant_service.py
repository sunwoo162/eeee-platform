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

    result = service.route("웹 앱 만들어줘")

    assert result.status == "blocked"
    assert result.project_id is not None
    assert "stale project revision" in result.message
    assert result.response_verification.decision == "BLOCKED"


def test_assistant_service_does_not_create_project_for_an_ambiguous_request(tmp_path) -> None:
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

    result = service.route("앱 만들어줘")

    assert result.status == "needs_clarification"
    assert result.project_id is None
    assert result.project_profile is None
    assert "확인" in result.message or "알려" in result.message


def test_assistant_service_does_not_claim_completion_when_response_verification_blocks(tmp_path) -> None:
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

    class BlockedResponseEnvelope:
        error = None
        execution_id = "execution-1"

        def route(self, *args, **kwargs):
            return self

        @staticmethod
        def model_dump(mode="json"):
            return {"output": {
                "status": "completed",
                "message": "완료했어.",
                "qualityStatus": "PASS",
                "projectId": "project-1",
                "projectRevision": "1",
                "selection": {"status": "selected", "capability_id": "project-execution"},
                "responseVerification": {
                    "decision": "BLOCKED",
                    "reason": "검증 증거가 부족해.",
                    "profile_version": "claimlatch-v0.2.0",
                    "subject_id": "execution-1",
                },
            }}

    service.kernel = BlockedResponseEnvelope()
    result = service.route("웹 앱 만들어줘")

    assert result.status == "blocked"
    assert result.message == "검증 증거가 부족해.", result


def test_assistant_service_blocks_completed_status_without_quality_evidence(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    service = AssistantService(
        router=CapabilityRouter(build_default_registry()),
        coordinator=Coordinator(store),
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
    )

    class IncompleteResponseEnvelope:
        error = None
        execution_id = "execution-2"

        def route(self, *args, **kwargs):
            return self

        @staticmethod
        def model_dump(mode="json"):
            return {"output": {
                "status": "completed",
                "message": "완료했어.",
                "projectId": "project-2",
                "projectRevision": "1",
                "selection": {"status": "selected", "capability_id": "project-execution"},
                "responseVerification": {
                    "decision": "BLOCKED",
                    "reason": "완료 증거가 없어.",
                    "profile_version": "claimlatch-v0.2.0",
                    "subject_id": "execution-2",
                },
            }}

    service.kernel = IncompleteResponseEnvelope()

    result = service.route("웹 앱 만들어줘")

    assert result.status == "blocked"
    assert result.message == "완료 증거가 없어.", result
