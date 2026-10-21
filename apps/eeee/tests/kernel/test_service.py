import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.assistant.models import AssistantContext, AssistantRequest, CapabilityDescriptor
from app.assistant.registry import build_default_registry
from app.assistant.router import CapabilityRouter
from app.config import Settings
from app.contracts import ExecutionStatus, LocalEventBus
from app.coordinator.service import Coordinator
from app.kernel.service import KernelService
from app.kernel.capabilities import LocalPlanningCapability
from app.main import create_app
from app.project_runtime.provisioner import ProjectProvisioner
from app.runtime.store import ExecutionStore
from app.storage.sqlite import SQLiteStore
from app.trust.gate import TrustGate
from app.trust.models import TrustCheck


def make_kernel(tmp_path, *, provisioner_type=ProjectProvisioner, coordinator_type=Coordinator,
                trust_gate=None):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    events = LocalEventBus()
    coordinator = coordinator_type(store, trust_gate=trust_gate) if trust_gate is not None else coordinator_type(store)
    kernel = KernelService(
        router=CapabilityRouter(build_default_registry()),
        coordinator=coordinator, store=store, settings=settings,
        provisioner=provisioner_type(store), event_bus=events, trust_gate=trust_gate,
    )
    return kernel, store, events


def test_project_request_persists_parent_and_fixed_project_child_with_lifecycle(tmp_path):
    kernel, store, bus = make_kernel(tmp_path)

    parent = kernel.route(AssistantRequest(raw_text="Todo 앱 만들어줘"), AssistantContext())

    assert parent.status == ExecutionStatus.BLOCKED
    assert parent.capability_id == "project-execution"
    assert parent.project_id is None
    assert parent.output["projectId"]
    executions = ExecutionStore(store)
    child = executions.get(parent.output["childExecutionId"])
    assert child.status == ExecutionStatus.BLOCKED
    assert child.project_id == parent.output["projectId"]
    assert child.project_revision == store.get_project(child.project_id).revision
    assert child.request_id == parent.output["coordinatorRequestId"]
    assert child.request_id != parent.request_id
    assert child.input["parentExecutionId"] == parent.execution_id
    assert executions.get(parent.execution_id) == parent
    assert child.output["projectProfile"]["projectId"] == child.project_id
    event_types = [event.event_type for event in bus.replay()]
    assert "assistant.route.started" in event_types
    assert "project.created" in event_types
    created = next(event for event in bus.replay() if event.event_type == "project.created")
    assert created.payload["projectRevision"] == child.project_revision
    assert event_types[-1] == "assistant.route.completed"
    child_events = executions.replay_events(project_id=child.project_id)
    assert [event.event_type for event in child_events if event.event_type.startswith("execution.")] == [
        "execution.queued", "execution.running", "execution.blocked"
    ]


def test_todo_request_runs_local_qa_and_exposes_claimlatch_release_block(tmp_path):
    kernel, store, _ = make_kernel(tmp_path)

    result = kernel.route(AssistantRequest(raw_text="Todo 앱 만들어줘"), AssistantContext())
    workspace = store.get_project(result.output["projectId"]).workspace

    assert result.output["qualityStatus"] == "BLOCKED"
    assert result.output["qaReportPath"]
    assert result.output["releaseManifestPath"] is None
    assert Path(workspace, "QA_REPORT.json").is_file()


def test_routing_record_exists_before_project_allocation(tmp_path):
    class ObservingCoordinator(Coordinator):
        def create_project(self, *args, **kwargs):
            with sqlite3.connect(self.store.path) as connection:
                rows = connection.execute(
                    "SELECT project_id, status FROM execution_envelopes"
                ).fetchall()
            assert rows == [(None, "running")]
            return super().create_project(*args, **kwargs)

    kernel, _, _ = make_kernel(tmp_path, coordinator_type=ObservingCoordinator)
    result = kernel.route(AssistantRequest(raw_text="Todo 앱 만들어줘"), AssistantContext())
    assert result.status == ExecutionStatus.BLOCKED


def test_non_project_and_explicit_capability_requests_do_not_allocate_project(tmp_path):
    kernel, store, _ = make_kernel(tmp_path)
    reminder = kernel.route(AssistantRequest(raw_text="내일 오후 3시에 회의 알려줘"), AssistantContext())
    explicit = kernel.route(
        AssistantRequest(raw_text="문서 검색해줘: 프로젝트", requested_capability="knowledge-documents"),
        AssistantContext(user_preferences={"language": "ko"}),
    )

    assert reminder.capability_id == "personal-secretary"
    assert explicit.capability_id == "knowledge-documents"
    assert reminder.output["status"] == "completed"
    assert reminder.output["capabilityStatus"] == "completed"
    assert reminder.output["reminder"]["title"] == "회의"
    assert explicit.output["status"] == "completed"
    assert explicit.output["capabilityStatus"] == "completed"
    assert explicit.output["documents"] == ()
    assert reminder.project_id is None
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM execution_envelopes").fetchone()[0] == 2


def test_general_conversation_is_handled_by_eeee_without_project_allocation(tmp_path):
    kernel, store, _ = make_kernel(tmp_path)

    result = kernel.route(
        AssistantRequest(raw_text="안녕, 오늘 기분이 어때?"), AssistantContext()
    )

    assert result.capability_id == "general-conversation"
    assert result.output["status"] == "completed"
    assert result.output["capabilityStatus"] == "completed"
    assert result.output["projectId"] is None if "projectId" in result.output else True
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0


def test_explicit_user_preference_is_saved_and_reused_on_next_request(tmp_path):
    kernel, store, _ = make_kernel(tmp_path)

    remembered = kernel.route(AssistantRequest(raw_text="앞으로 한국어로 답해줘"), AssistantContext())
    next_request = kernel.route(AssistantRequest(raw_text="내일 오후 3시에 회의 알려줘"), AssistantContext())

    assert remembered.capability_id == "user-preference"
    assert remembered.output["status"] == "completed"
    assert next_request.output["reminder"]["title"] == "회의"


def test_ambiguous_request_is_auditable_and_requires_clarification(tmp_path):
    kernel, store, _ = make_kernel(tmp_path)
    result = kernel.route(AssistantRequest(raw_text="이거 해줘"), AssistantContext())
    assert result.status == ExecutionStatus.BLOCKED
    assert result.output["status"] == "needs_clarification"
    assert ExecutionStore(store).get(result.execution_id) == result


def test_allocation_failure_is_persisted_without_success(tmp_path):
    class BrokenCoordinator(Coordinator):
        def create_project(self, *args, **kwargs):
            raise RuntimeError("allocation failed")

    kernel, store, _ = make_kernel(tmp_path, coordinator_type=BrokenCoordinator)
    result = kernel.route(AssistantRequest(raw_text="앱 만들어줘"), AssistantContext())
    assert result.status == ExecutionStatus.FAILED
    assert result.error.message == "allocation failed"
    assert ExecutionStore(store).get(result.execution_id) == result


def test_child_failure_is_recorded_and_parent_does_not_claim_project_success(tmp_path):
    class BrokenProvisioner(ProjectProvisioner):
        def provision(self, *args, **kwargs):
            raise RuntimeError("provision failed")

    kernel, store, _ = make_kernel(tmp_path, provisioner_type=BrokenProvisioner)
    result = kernel.route(AssistantRequest(raw_text="앱 만들어줘"), AssistantContext())
    assert result.status == ExecutionStatus.FAILED
    child = ExecutionStore(store).get(result.output["childExecutionId"])
    assert child.status == ExecutionStatus.FAILED
    assert child.error.message == "provision failed"
    assert result.output["status"] == "blocked"


def test_stale_project_context_blocks_before_capability_execution(tmp_path):
    kernel, store, _ = make_kernel(tmp_path)
    store.create_project("existing", "Existing", str(tmp_path / "existing"), revision="rev-2")
    result = kernel.route(
        AssistantRequest(raw_text="앱 만들어줘", context={"projectId": "existing", "projectRevision": "rev-1"}),
        AssistantContext(),
    )
    assert result.status == ExecutionStatus.BLOCKED
    assert "stale" in result.output["message"]
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


def test_required_trust_gate_blocks_project_action_with_auditable_child(tmp_path):
    kernel, store, _ = make_kernel(tmp_path, trust_gate=TrustGate(None, mode="required"))
    result = kernel.route(AssistantRequest(raw_text="앱 만들어줘"), AssistantContext())
    assert result.status == ExecutionStatus.BLOCKED
    child = ExecutionStore(store).get(result.output["childExecutionId"])
    assert child.status == ExecutionStatus.BLOCKED
    assert child.output["trust"]["decision"] == "BLOCKED"


def test_create_app_wires_one_kernel_and_builtin_handlers_without_plugins(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces"))
    assert app.state.assistant_service.kernel is app.state.kernel
    assert app.state.kernel.memory is app.state.coordinator.memory
    assert app.state.kernel.trust_gate is app.state.trust_gate
    for descriptor in app.state.kernel.router.registry.list():
        handler = app.state.kernel.router.registry.resolve(descriptor.id).handler
        assert handler.descriptor is descriptor
        assert callable(handler.plan)
        assert callable(handler.execute)
    assert app.state.kernel.router.registry.resolve("project-execution").descriptor.required_connectors == []


def test_english_trigger_inside_unrelated_word_does_not_create_project(tmp_path):
    kernel, store, _ = make_kernel(tmp_path)
    result = kernel.route(AssistantRequest(raw_text="I am happy"), AssistantContext())
    assert result.status == ExecutionStatus.COMPLETED
    assert result.capability_id == "general-conversation"
    assert result.capability_id == "general-conversation"
    assert result.output["capabilityStatus"] == "completed"
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
    project = kernel.route(AssistantRequest(raw_text="Build a todo app"), AssistantContext())
    assert project.capability_id == "project-execution"
    assert project.status == ExecutionStatus.BLOCKED


def test_request_creation_failure_keeps_allocated_project_link_in_parent(tmp_path):
    class BrokenRequestCoordinator(Coordinator):
        def create_request(self, *args, **kwargs):
            raise RuntimeError("request creation failed")

    kernel, store, _ = make_kernel(tmp_path, coordinator_type=BrokenRequestCoordinator)
    result = kernel.route(AssistantRequest(raw_text="앱 만들어줘"), AssistantContext())
    assert result.status == ExecutionStatus.FAILED
    assert store.get_project(result.output["projectId"]).id == result.output["projectId"]
    assert result.error.message == "request creation failed"
    assert ExecutionStore(store).get(result.execution_id) == result


def test_initial_stale_child_rejection_keeps_project_and_request_on_parent(tmp_path):
    class RevisionAdvancingCoordinator(Coordinator):
        def create_request(self, project_id, text):
            state = super().create_request(project_id, text)
            self.store.update_project_revision(project_id, "rev-after-request")
            return state

    kernel, store, _ = make_kernel(tmp_path, coordinator_type=RevisionAdvancingCoordinator)
    result = kernel.route(AssistantRequest(raw_text="앱 만들어줘"), AssistantContext())

    assert result.status == ExecutionStatus.FAILED
    assert result.error.code == "stale_project_revision"
    assert result.output["status"] == "blocked"
    assert result.output["projectId"]
    assert result.output["coordinatorRequestId"]
    assert "childExecutionId" not in result.output
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM execution_envelopes WHERE project_id = ?",
            (result.output["projectId"],),
        ).fetchone()[0] == 0


def test_trust_gate_exception_terminalizes_child_and_parent_without_provisioning(tmp_path):
    class BrokenTrustGate(TrustGate):
        def verify_action(self, **kwargs):
            raise RuntimeError("trust engine failed")

    kernel, store, _ = make_kernel(tmp_path, trust_gate=BrokenTrustGate(None))
    result = kernel.route(AssistantRequest(raw_text="앱 만들어줘"), AssistantContext())
    assert result.status == ExecutionStatus.FAILED
    child = ExecutionStore(store).get(result.output["childExecutionId"])
    assert child.status == ExecutionStatus.FAILED
    assert child.error.message == "trust engine failed"
    assert not kernel.router.registry.resolve("project-execution").handler.settings.workspace_root.exists()


def test_capability_requiring_approval_only_executes_when_approved(tmp_path):
    kernel, store, _ = make_kernel(tmp_path)
    descriptor = CapabilityDescriptor(
        id="approved-local", version="1.0", display_name="Local", approval_level="user",
        intents=["plan"], trigger_phrases=["plan"], side_effect_level="none",
        claim_latch_policy="claimlatch-v0.2.0",
    )
    kernel.router.registry.register(descriptor, LocalPlanningCapability(descriptor))
    denied = kernel.route(
        AssistantRequest(raw_text="plan", requested_capability="approved-local"), AssistantContext(),
    )
    assert denied.status == ExecutionStatus.AWAITING_APPROVAL
    assert "plan" not in denied.output
    approved = kernel.route(
        AssistantRequest(
            raw_text="plan", requested_capability="approved-local",
            context={"approved": True, "approvalRequestId": denied.execution_id},
        ),
        AssistantContext(),
    )
    assert approved.status == ExecutionStatus.COMPLETED
    assert approved.output["capabilityStatus"] == "planned"
    assert ExecutionStore(store).get(approved.execution_id).approval_state.value == "approved"


def test_revision_advancing_during_provisioning_records_child_and_parent_failure(tmp_path):
    class RevisionAdvancingProvisioner(ProjectProvisioner):
        def provision(self, project, *args, **kwargs):
            result = super().provision(project, *args, **kwargs)
            self.store.update_project_revision(project.id, "rev-new")
            return result

    kernel, store, bus = make_kernel(tmp_path, provisioner_type=RevisionAdvancingProvisioner)
    result = kernel.route(AssistantRequest(raw_text="앱 만들어줘"), AssistantContext())
    assert result.status == ExecutionStatus.FAILED
    child = ExecutionStore(store).get(result.output["childExecutionId"])
    assert child.status == ExecutionStatus.FAILED
    assert child.error.code == "stale_project_revision"
    assert result.error.code == "stale_project_revision"
    assert child.output["status"] == "blocked"
    assert "projectProfile" not in child.output
    assert not any(event.event_type == "execution.completed" for event in bus.replay())


def test_completion_and_event_are_atomic_when_revision_advances_after_commit(tmp_path):
    class PassingTrustGate(TrustGate):
        def verify_action(self, **kwargs):
            return TrustCheck(
                subject_id=kwargs["subject_id"], project_id=kwargs["project_id"],
                project_revision=kwargs["project_revision"], action=kwargs["action"],
                decision="PASS", report_id="claim-report", receipt_id="receipt", reason="pass",
            )

    kernel, store, bus = make_kernel(tmp_path, trust_gate=PassingTrustGate(None))
    connect = store._connect
    advanced = False

    @contextmanager
    def connection_with_revision_race():
        nonlocal advanced
        with connect() as connection:
            yield connection
            completed = connection.execute(
                "SELECT project_id FROM execution_envelopes WHERE tool_id = 'iseol' AND status = 'completed'"
            ).fetchone()
        if completed is not None and not advanced:
            advanced = True
            # Simulate another writer immediately after the completion commit.
            store.update_project_revision(completed["project_id"], "rev-next")

    store._connect = connection_with_revision_race
    result = kernel.route(AssistantRequest(raw_text="앱 만들어줘"), AssistantContext())
    assert advanced
    assert result.status == ExecutionStatus.COMPLETED
    child = ExecutionStore(store).get(result.output["childExecutionId"])
    assert store.get_project(child.project_id).revision == "rev-next"
    completed = [event for event in ExecutionStore(store).replay_events(project_id=child.project_id)
                 if event.event_type == "execution.completed"]
    assert len(completed) == 1
    assert completed[0].project_revision == child.project_revision == "initial"
    published = [event for event in bus.replay(project_id=child.project_id)
                 if event.event_type == "execution.completed"]
    assert published[0].payload["durableCursor"] == completed[0].cursor
