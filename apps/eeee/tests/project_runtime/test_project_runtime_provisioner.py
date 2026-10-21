from pathlib import Path

from app.domain.models import PetState, Project, RequestBrief
from app.project_runtime.provisioner import ProjectProvisioner
from app.iseol.intake import NaturalLanguageIntake
from app.storage.sqlite import SQLiteStore


def request() -> RequestBrief:
    return RequestBrief(
        raw_text="웹 프로젝트 하나 만들어줘",
        goal="Build a web project",
        target_type="web_app",
        constraints=["local-first"],
        acceptance_criteria=["runs locally"],
    )


def project(workspace: Path) -> Project:
    return Project(
        id="project-1",
        name="Assistant project",
        workspace=str(workspace),
        revision="rev-1",
        state=PetState.idle,
        active_task_id=None,
    )


def test_provisioning_creates_one_profile_and_truthful_connector_plans(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    provisioner = ProjectProvisioner(store)

    result = provisioner.provision(
        project(tmp_path / "workspace"),
        request(),
        memory_ids=["memory-1"],
        qa_baseline_ids=["qa-1"],
    )

    assert Path(result.profile.workspace).is_dir()
    assert result.profile.runtime_profile == "web_app"
    assert result.profile.capabilities == ["project-execution"]
    assert {item.connector_id for item in result.profile.connectors} == {
        "notion",
        "google-calendar",
        "github",
        "iseol-runtime",
        "desktop",
        "mobile-bridge",
    }
    assert result.profile.provisioning_status == "awaiting_configuration"
    assert result.profile.connector("notion").state == "awaiting_configuration"
    assert result.profile.connector("iseol-runtime").state == "ready"
    assert result.profile.connector("desktop").state == "ready"
    assert result.profile.connector("mobile-bridge").state == "ready"
    assert result.missing_connectors == ["github", "google-calendar", "notion"]


def test_provisioning_reads_connected_connector_ids_at_execution_time(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    connected = {"notion"}
    provisioner = ProjectProvisioner(
        store,
        configured_connector_ids=lambda: set(connected),
    )

    result = provisioner.provision(
        project(tmp_path / "workspace"),
        request(),
        memory_ids=[],
        qa_baseline_ids=[],
    )

    assert result.profile.connector("notion").state == "planned"
    assert "notion" not in result.missing_connectors


def test_repeated_provisioning_is_idempotent_and_survives_store_reopen(tmp_path) -> None:
    database = tmp_path / "state.sqlite3"
    store = SQLiteStore(database)
    store.init()
    provisioner = ProjectProvisioner(store)
    input_project = project(tmp_path / "workspace")

    first = provisioner.provision(input_project, request(), memory_ids=[], qa_baseline_ids=[])
    second = provisioner.provision(input_project, request(), memory_ids=[], qa_baseline_ids=[])
    reopened = SQLiteStore(database)
    reopened.init()

    assert second.profile == first.profile
    assert reopened.get_project_profile("project-1") == first.profile
    assert len(first.profile.connectors) == len(second.profile.connectors)


def test_todo_request_provisions_an_actual_fsd_project(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    provisioner = ProjectProvisioner(store)
    todo_request = RequestBrief(
        raw_text="Todo 앱 만들어줘",
        goal="Todo 앱 만들어줘",
        target_type="todo_app",
        constraints=["local-first"],
        acceptance_criteria=["todo can be added and completed"],
    )

    provisioner.provision(
        project(tmp_path / "todo-workspace"),
        todo_request,
        memory_ids=[],
        qa_baseline_ids=[],
    )

    assert (tmp_path / "todo-workspace" / "index.html").is_file()
    assert (tmp_path / "todo-workspace" / "src" / "entities" / "todo" / "model.js").is_file()


def test_web_request_provisions_a_full_stack_project_boundary(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    provisioner = ProjectProvisioner(store)

    provisioner.provision(
        project(tmp_path / "web-workspace"),
        request(),
        memory_ids=[],
        qa_baseline_ids=[],
    )

    root = tmp_path / "web-workspace"
    assert (root / "apps" / "web" / "index.html").is_file()
    assert (root / "apps" / "api" / "server.py").is_file()
    assert (root / ".env.example").is_file()


def test_meal_intent_provisions_selected_template_and_records_it(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    provisioner = ProjectProvisioner(store)
    intent = NaturalLanguageIntake.parse("오늘 식단 정리해주는 웹 만들어줘").intent

    result = provisioner.provision(
        project(tmp_path / "meal-workspace"),
        intent.to_request_brief(),
        memory_ids=[],
        qa_baseline_ids=[],
        intent=intent,
    )

    root = tmp_path / "meal-workspace"
    assert result.profile.template_id == "meal_planner"
    assert (root / "apps/web/src/entities/meal/model.js").is_file()
    assert "meal_planner" in (root / "DESIGN.md").read_text(encoding="utf-8")
    assert '"templateId": "meal_planner"' in (root / "PROJECT_PROFILE.json").read_text(encoding="utf-8")

