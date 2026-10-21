from app.domain.models import PetState, ReportRecord
from app.storage.sqlite import SQLiteStore


def test_project_task_report_and_ordered_events_survive_store_reopen(tmp_path):
    database = tmp_path / "project.sqlite3"
    store = SQLiteStore(database)
    store.init()

    project = store.create_project(
        "project-1", "Demo project", str(tmp_path / "workspace"), revision="rev-1"
    )
    task = store.create_task(project.id, "request-1", project.revision)
    assert task.state == PetState.researching

    updated = store.update_task(
        task.id,
        PetState.completed,
        "Verification passed",
        required_action=None,
        revision="rev-1",
        report_id="report-1",
        report={"summary": "All checks passed"},
    )
    assert updated.report_id == "report-1"

    report = ReportRecord(
        id="report-1",
        project_id=project.id,
        task_id=task.id,
        revision="rev-1",
        status="passed",
        summary="All checks passed",
        checks=[{"name": "tests", "status": "passed"}],
    )
    store.save_report(report)
    store.append_task_event(task.id, {"action": "started", "sequence": 1})
    store.append_task_event(task.id, {"action": "verified", "sequence": 2})
    store.update_project_revision(project.id, "rev-2")

    reopened = SQLiteStore(database)
    reopened.init()
    assert reopened.get_project(project.id).revision == "rev-2"
    assert reopened.get_task(task.id) == updated
    assert reopened.get_report("report-1") == report
    assert reopened.get_task_events(task.id) == [
        {"action": "started", "sequence": 1},
        {"action": "verified", "sequence": 2},
    ]


def test_project_owner_is_persisted_and_enforced_after_reopen(tmp_path):
    database = tmp_path / "project-owner.sqlite3"
    store = SQLiteStore(database)
    store.init()
    store.create_project(
        "owned-project", "Owned", str(tmp_path / "workspace"), user_id="user-a"
    )

    reopened = SQLiteStore(database)
    reopened.init()
    assert reopened.get_project("owned-project", user_id="user-a").user_id == "user-a"
    try:
        reopened.get_project("owned-project", user_id="user-b")
    except KeyError:
        pass
    else:
        raise AssertionError("a project must not be readable by another user")
