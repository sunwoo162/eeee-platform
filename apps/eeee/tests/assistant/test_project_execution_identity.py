from pathlib import Path

from app.assistant.models import AssistantContext, AssistantRequest
from app.assistant.registry import build_default_registry
from app.assistant.router import CapabilityRouter
from app.assistant.service import AssistantService
from app.config import Settings
from app.coordinator.service import Coordinator
from app.kernel.capabilities import ProjectExecutionCapability
from app.project_runtime.provisioner import ProjectProvisioner
from app.storage.sqlite import SQLiteStore


class RecordingSupervisor:
    def __init__(self) -> None:
        self.input_data: dict[str, object] | None = None

    def submit(self, request_id, operation, *, input_data=None):
        self.input_data = dict(input_data or {})
        return "assistant-job-test"


def _service(tmp_path, supervisor):
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
    )


def test_accepted_project_request_persists_a_stable_project_identity(tmp_path) -> None:
    supervisor = RecordingSupervisor()
    result = _service(tmp_path, supervisor).route("Todo 앱 만들어줘")

    assert result.status == "accepted"
    assert result.project_id
    assert supervisor.input_data is not None
    assert supervisor.input_data["projectId"] == result.project_id


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
        context={"resumeProjectId": "project-resume-1"},
    )

    plan = capability.plan(request, AssistantContext())

    assert plan.inputs["projectId"] == "project-resume-1"
    assert Path(plan.inputs["workspace"]).is_relative_to(settings.workspace_root)

