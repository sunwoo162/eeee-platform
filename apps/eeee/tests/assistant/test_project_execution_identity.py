from pathlib import Path

import pytest

from app.assistant.models import AssistantContext, AssistantRequest
from app.assistant.registry import build_default_registry
from app.assistant.router import CapabilityRouter
from app.assistant.service import AssistantService
from app.config import Settings
from app.coordinator.service import Coordinator
from app.kernel.capabilities import ProjectExecutionCapability
from app.kernel.capabilities import EnvelopeContext
from app.project_runtime.provisioner import ProjectProvisioner
from app.storage.sqlite import SQLiteStore
from app.conversations.store import ConversationStore


class RecordingSupervisor:
    def __init__(self) -> None:
        self.input_data: dict[str, object] | None = None
        self.operation = None
        self.submit_count = 0
        self.job_id = "assistant-job-test"

    def submit(self, request_id, operation, *, input_data=None):
        self.input_data = dict(input_data or {})
        self.operation = operation
        self.submit_count += 1
        self.request_id = request_id
        return self.job_id

    def find_by_request_id(self, request_id, *, user_id="local-user"):
        if request_id != getattr(self, "request_id", None):
            return None
        if user_id != self.input_data.get("userId", "local-user"):
            return None
        return {
            "jobId": self.job_id,
            "requestId": request_id,
            "status": "running",
            "input": self.input_data or {},
            "result": None,
        }


def _service(tmp_path, supervisor, *, canonical: bool = False):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    return AssistantService(
        router=CapabilityRouter(build_default_registry()),
        coordinator=Coordinator(store),
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
        background_supervisor=supervisor,
        conversation_store=ConversationStore(store) if canonical else None,
    )


def test_accepted_project_request_persists_a_stable_project_identity(tmp_path) -> None:
    supervisor = RecordingSupervisor()
    result = _service(tmp_path, supervisor).route("Todo 앱 만들어줘")

    assert result.status == "accepted"
    assert result.project_id
    assert supervisor.input_data is not None
    assert supervisor.input_data["projectId"] == result.project_id


def test_retry_without_request_id_attaches_to_existing_background_project(tmp_path) -> None:
    supervisor = RecordingSupervisor()
    service = _service(tmp_path, supervisor, canonical=True)

    first = service.route("Todo 앱 만들어줘", conversation_id="retry-safe")
    second = service.route("Todo 앱 만들어줘", conversation_id="retry-safe")

    assert first.status == "accepted"
    assert second.status == "accepted"
    assert second.job_id == first.job_id
    assert second.project_id == first.project_id
    assert supervisor.submit_count == 1


def test_background_failure_replaces_pending_canonical_reply(tmp_path) -> None:
    supervisor = RecordingSupervisor()
    service = _service(tmp_path, supervisor, canonical=True)
    conversation_store = service.conversation_store

    service.route("Todo 앱 만들어줘", conversation_id="failed-background")
    service._route_sync = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("작업 실패"))

    assert supervisor.operation is not None
    with pytest.raises(RuntimeError, match="작업 실패"):
        supervisor.operation()

    assert conversation_store is not None
    turns = conversation_store.get_transcript("failed-background")["turns"]
    assert turns[1]["status"] == "failed"
    assert "작업 실패" in turns[1]["content"]


def test_background_project_result_replaces_accepted_turn_in_conversation_memory(tmp_path) -> None:
    supervisor = RecordingSupervisor()
    service = _service(tmp_path, supervisor)

    accepted = service.route("Todo 앱 만들어줘", conversation_id="background-history")
    assert accepted.status == "accepted"
    assert supervisor.operation is not None
    assert len(service.coordinator.memory.recent_conversation_turns("background-history")) == 2

    class FinalResult:
        message = "프로젝트가 검증을 마쳤지만 릴리스는 차단됐어."

        def model_dump(self, mode="json"):
            return {"message": self.message, "status": "blocked"}

    service._route_sync = lambda *args, **kwargs: FinalResult()
    supervisor.operation()

    turns = service.coordinator.memory.recent_conversation_turns("background-history", limit=10)
    assert len(turns) == 2
    assert turns[0]["content"] == "Todo 앱 만들어줘"
    assert turns[1] == {"role": "assistant", "content": FinalResult.message}


def test_project_plan_reuses_resume_project_identity(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    descriptor = build_default_registry().resolve("project-execution").descriptor
    capability = ProjectExecutionCapability(
        descriptor,
        coordinator=Coordinator(store),
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
    )
    request = AssistantRequest(
        raw_text="Todo 앱 만들어줘",
        context={"resumeProjectId": "project-resume-1", "userId": "user-a"},
    )

    plan = capability.plan(request, AssistantContext())

    assert plan.inputs["projectId"] == "project-resume-1"
    assert Path(plan.inputs["workspace"]).is_relative_to(settings.workspace_root)
    assert plan.inputs["userId"] == "user-a"


def test_project_plan_preserves_external_action_approval_context(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    descriptor = build_default_registry().resolve("project-execution").descriptor
    capability = ProjectExecutionCapability(
        descriptor,
        coordinator=Coordinator(store),
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
    )

    plan = capability.plan(
        AssistantRequest(
            raw_text="카페 홈페이지 배포해줘",
            context={"approved": True},
        ),
        AssistantContext(),
    )

    assert plan.inputs["requiresExternalApproval"] is True
    assert plan.inputs["externalActions"]
    assert plan.inputs["approved"] is True


def test_project_execution_passes_external_action_context_to_orchestrator(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    descriptor = build_default_registry().resolve("project-execution").descriptor
    capability = ProjectExecutionCapability(
        descriptor,
        coordinator=Coordinator(store),
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
    )
    plan = capability.plan(
        AssistantRequest(raw_text="카페 홈페이지 배포해줘"),
        AssistantContext(),
    )
    seen: dict[str, object] = {}

    class RecordingOrchestrator:
        def run(self, request, _context, _envelope):
            seen.update(request.context)
            return {"status": "blocked"}

    capability.orchestrator = RecordingOrchestrator()
    capability.execute(
        plan,
        EnvelopeContext(
            envelope=object(),
            assistant_context=AssistantContext(),
            run_child=lambda **_kwargs: None,
        ),
    )

    assert seen["externalActionRequired"] is True
    assert seen["approved"] is False
    assert seen["externalActions"]


def test_project_execution_preserves_user_context_for_orchestrator(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    descriptor = build_default_registry().resolve("project-execution").descriptor
    capability = ProjectExecutionCapability(
        descriptor,
        coordinator=Coordinator(store),
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
    )
    plan = capability.plan(
        AssistantRequest(raw_text="Todo 앱 만들어줘", context={"userId": "user-a"}),
        AssistantContext(),
    )
    seen: dict[str, object] = {}

    class RecordingOrchestrator:
        def run(self, request, _context, _envelope):
            seen.update(request.context)
            return {"status": "blocked"}

    capability.orchestrator = RecordingOrchestrator()
    capability.execute(
        plan,
        EnvelopeContext(
            envelope=object(),
            assistant_context=AssistantContext(),
            run_child=lambda **_kwargs: None,
        ),
    )

    assert seen["userId"] == "user-a"

