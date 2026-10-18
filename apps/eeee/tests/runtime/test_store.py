"""Durable execution and plugin-registration behavior at the SQLite boundary."""

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from app.contracts import ApprovalState, EventEnvelope, ExecutionEnvelope, ExecutionError, ExecutionStatus, SideEffectLevel
from app.runtime.store import ExecutionStore, PluginRegistrationStore
from app.storage.sqlite import SQLiteStore


def _envelope(**updates: object) -> ExecutionEnvelope:
    values: dict[str, object] = {
        "execution_id": "execution-1",
        "request_id": "request-1",
        "project_id": "project-1",
        "project_revision": "rev-1",
        "capability_id": "project-execution",
        "tool_id": "iseol",
        "actor": "EEEE",
        "input": {"request": "Todo 앱 만들어줘", "options": ["local"]},
        "evidence_ids": ("evidence-1",),
        "claim_latch_receipt_id": "claim-1",
        "qa_report_id": "qa-1",
        "started_at": datetime(2026, 10, 6, 1, 2, 3, tzinfo=timezone.utc),
    }
    values.update(updates)
    return ExecutionEnvelope(**values)


def _event(*, execution_id: str = "execution-1", revision: str = "rev-1") -> EventEnvelope:
    return EventEnvelope(
        event_type="execution.running",
        execution_id=execution_id,
        request_id="request-1",
        project_id="project-1",
        project_revision=revision,
        payload={"progress": ["start"]},
        published_at=datetime(2026, 10, 6, 1, 2, 3, tzinfo=timezone.utc),
    )


def _store(tmp_path) -> SQLiteStore:
    store = SQLiteStore(tmp_path / "runtime.sqlite3")
    store.init()
    store.create_project("project-1", "Todo", str(tmp_path / "workspace"), revision="rev-1")
    return store


def test_envelope_round_trip_preserves_revision_trust_and_evidence_after_restart(tmp_path) -> None:
    store = _store(tmp_path)
    execution = ExecutionStore(store)
    queued = _envelope()
    execution.save(queued)
    running = queued.transition(ExecutionStatus.RUNNING)
    execution.save(running)
    completed = running.transition(
        ExecutionStatus.COMPLETED,
        at=queued.started_at + timedelta(minutes=1),
        output={"result": {"files": ["README.md"]}},
    )
    execution.save(completed)

    reopened = ExecutionStore(SQLiteStore(store.path))
    loaded = reopened.get("execution-1")
    assert loaded == completed
    assert loaded.project_revision == "rev-1"
    assert loaded.claim_latch_receipt_id == "claim-1"
    assert loaded.qa_report_id == "qa-1"
    assert loaded.evidence_ids == ("evidence-1",)
    assert loaded.model_dump(mode="json", by_alias=True)["output"] == {"result": {"files": ["README.md"]}}


def test_project_listing_filters_revision_and_retains_historical_envelopes(tmp_path) -> None:
    store = _store(tmp_path)
    executions = ExecutionStore(store)
    executions.save(_envelope())
    store.update_project_revision("project-1", "rev-2")
    executions.save(_envelope(execution_id="execution-2", project_revision="rev-2"))

    assert [item.execution_id for item in executions.list_for_project("project-1")] == [
        "execution-1", "execution-2"
    ]
    assert [item.execution_id for item in executions.list_for_project("project-1", "rev-1")] == [
        "execution-1"
    ]
    assert [item.execution_id for item in executions.list_for_project("project-1", "rev-2")] == [
        "execution-2"
    ]


def test_approval_claim_is_atomic_and_plugin_routes_are_listed_newest_first(tmp_path) -> None:
    store = _store(tmp_path)
    executions = ExecutionStore(store)
    waiting = _envelope(
        execution_id="approval-1",
        capability_id="plugin:gmail:mail.send",
        tool_id="eeee.route",
        required_approval=True,
        approval_state=ApprovalState.AWAITING_APPROVAL,
    ).transition(
        ExecutionStatus.AWAITING_APPROVAL,
        output={
            "status": "blocked",
            "approvalRequired": True,
            "approvalRequestId": "approval-1",
        },
    )
    executions.save(waiting)

    claimed, was_claimed = executions.claim_approval("approval-1")
    repeated, repeated_claim = executions.claim_approval("approval-1")

    assert was_claimed is True
    assert claimed.status is ExecutionStatus.RUNNING
    assert claimed.approval_state is ApprovalState.APPROVED
    assert repeated == claimed
    assert repeated_claim is False
    assert executions.list_plugin_routes(limit=10) == [claimed]


def test_stale_revision_cannot_write_envelope_or_event(tmp_path) -> None:
    store = _store(tmp_path)
    executions = ExecutionStore(store)
    executions.save(_envelope())
    store.update_project_revision("project-1", "rev-2")

    with pytest.raises(ValueError, match="stale|revision"):
        executions.save(_envelope(execution_id="execution-2"))
    with pytest.raises(ValueError, match="stale|revision"):
        executions.append_event(_event())
    assert [item.execution_id for item in executions.list_for_project("project-1")] == ["execution-1"]
    assert executions.replay_events(project_id="project-1") == []


@pytest.mark.parametrize("status", [ExecutionStatus.FAILED, ExecutionStatus.BLOCKED, ExecutionStatus.CANCELLED])
def test_existing_stale_execution_can_record_only_failure_and_matching_event(tmp_path, status):
    store = _store(tmp_path)
    executions = ExecutionStore(store)
    running = _envelope().transition(ExecutionStatus.RUNNING)
    executions.save(running)
    store.update_project_revision("project-1", "rev-2")
    error = ExecutionError(code="stale_project_revision", message="stale project revision: rev-1")
    failed = running.transition(status, output={"status": "blocked", "message": error.message}, error=error)

    executions.save(failed)
    event = EventEnvelope(
        event_type=f"execution.{status.value}", execution_id=failed.execution_id,
        request_id=failed.request_id, project_id=failed.project_id, project_revision=failed.project_revision,
        payload={"status": status.value, "toolId": failed.tool_id, "parentExecutionId": None},
    )
    saved = executions.append_event(event)
    assert ExecutionStore(SQLiteStore(store.path)).get(failed.execution_id) == failed
    assert executions.replay_events(project_id="project-1") == [saved]
    with pytest.raises(ValueError, match="stale"):
        executions.append_event(EventEnvelope.model_validate({**event.model_dump(), "event_type": "execution.completed"}))
    with pytest.raises(ValueError, match="stale"):
        executions.save(ExecutionEnvelope.model_validate({**failed.model_dump(), "execution_id": "new-stale"}))


@pytest.mark.parametrize("changes", [
    {"evidence_ids": ("evidence-1", "unverified-evidence")},
    {"claim_latch_receipt_id": "new-receipt"},
    {"qa_report_id": "new-qa"},
    {"input": {"request": "changed"}},
    {"side_effect_level": SideEffectLevel.EXTERNAL},
    {"output": {"status": "ready", "trust": {"decision": "PASS"}}},
    {"error": ExecutionError(code="other_failure", message="not a stale failure")},
])
def test_stale_failure_cannot_enrich_audit_or_smuggle_success(tmp_path, changes):
    store = _store(tmp_path)
    executions = ExecutionStore(store)
    running = _envelope().transition(ExecutionStatus.RUNNING)
    executions.save(running)
    store.update_project_revision("project-1", "rev-2")
    failed = running.transition(
        ExecutionStatus.FAILED, error=ExecutionError(code="stale_project_revision", message="stale revision"),
    )
    altered = ExecutionEnvelope.model_validate({**failed.model_dump(), **changes})
    with pytest.raises(ValueError):
        executions.save(altered)
    assert executions.get(running.execution_id) == running


def test_stale_completed_output_is_rejected_even_for_existing_execution(tmp_path):
    store = _store(tmp_path)
    executions = ExecutionStore(store)
    running = _envelope().transition(ExecutionStatus.RUNNING)
    executions.save(running)
    store.update_project_revision("project-1", "rev-2")
    with pytest.raises(ValueError, match="stale"):
        executions.save(running.transition(ExecutionStatus.COMPLETED, output={"trust": {"decision": "PASS"}}))
    assert executions.get(running.execution_id) == running


def test_record_commits_execution_and_lifecycle_event_together(tmp_path):
    executions = ExecutionStore(_store(tmp_path))
    queued = _envelope()
    executions.save(queued)
    running = queued.transition(ExecutionStatus.RUNNING)
    event = executions.record(running, _event())
    assert executions.get(running.execution_id) == running
    assert event.cursor == 1
    assert executions.replay_events() == [event]


def test_record_rolls_back_state_update_when_event_identity_is_wrong(tmp_path):
    executions = ExecutionStore(_store(tmp_path))
    queued = _envelope()
    executions.save(queued)
    invalid = EventEnvelope.model_validate({**_event().model_dump(), "request_id": "wrong-request"})
    with pytest.raises(ValueError, match="identity"):
        executions.record(queued.transition(ExecutionStatus.RUNNING), invalid)
    assert executions.get(queued.execution_id) == queued
    assert executions.replay_events() == []


def test_record_rejects_an_event_for_another_existing_execution(tmp_path):
    executions = ExecutionStore(_store(tmp_path))
    queued = _envelope()
    executions.save(queued)
    executions.save(_envelope(execution_id="execution-2"))
    with pytest.raises(ValueError, match="identity"):
        executions.record(queued.transition(ExecutionStatus.RUNNING), _event(execution_id="execution-2"))
    assert executions.get(queued.execution_id) == queued
    assert executions.replay_events() == []


def test_record_supports_existing_stale_failure_but_not_stale_completion(tmp_path):
    store = _store(tmp_path)
    executions = ExecutionStore(store)
    running = _envelope().transition(ExecutionStatus.RUNNING)
    executions.save(running)
    store.update_project_revision("project-1", "rev-2")
    failed = running.transition(
        ExecutionStatus.FAILED, error=ExecutionError(code="stale_project_revision", message="stale revision"),
    )
    failure_event = EventEnvelope.model_validate({
        **_event().model_dump(), "event_type": "execution.failed",
        "payload": {"status": "failed", "toolId": "iseol", "parentExecutionId": None},
    })
    with pytest.raises(ValueError, match="stale"):
        executions.record(running.transition(ExecutionStatus.COMPLETED, output={"status": "ready"}), _event())
    assert executions.get(running.execution_id) == running
    assert executions.replay_events() == []
    recorded = executions.record(failed, failure_event)
    assert executions.get(failed.execution_id) == failed
    assert executions.replay_events() == [recorded]


def test_missing_project_and_identity_change_are_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    executions = ExecutionStore(store)
    with pytest.raises(KeyError, match="Project"):
        executions.save(_envelope(project_id="missing-project"))
    executions.save(_envelope())
    with pytest.raises(ValueError, match="identity|request"):
        executions.save(_envelope(request_id="another-request"))
    assert executions.get("execution-1").request_id == "request-1"


def test_terminal_execution_cannot_be_rewritten_as_another_result(tmp_path) -> None:
    executions = ExecutionStore(_store(tmp_path))
    queued = _envelope()
    completed = queued.transition(ExecutionStatus.RUNNING).transition(
        ExecutionStatus.COMPLETED,
        at=queued.started_at + timedelta(minutes=1),
        output={"result": "verified"},
    )
    executions.save(completed)
    forged = ExecutionEnvelope.model_validate(
        {**completed.model_dump(), "output": {"result": "unverified"}}
    )

    with pytest.raises(ValueError, match="terminal|completed"):
        executions.save(forged)
    assert executions.get("execution-1") == completed


@pytest.mark.parametrize(
    "changes",
    [
        {"required_approval": False, "approval_state": ApprovalState.NOT_REQUIRED},
        {"side_effect_level": SideEffectLevel.NONE},
    ],
)
def test_saved_approval_policy_cannot_be_weakened(tmp_path, changes: dict[str, object]) -> None:
    executions = ExecutionStore(_store(tmp_path))
    original = _envelope(
        required_approval=True,
        approval_state=ApprovalState.AWAITING_APPROVAL,
        side_effect_level=SideEffectLevel.EXTERNAL,
    )
    executions.save(original)
    weakened = ExecutionEnvelope.model_validate({**original.model_dump(), **changes})

    with pytest.raises(ValueError, match="identity|policy"):
        executions.save(weakened)
    assert executions.get("execution-1") == original


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_ids": ()},
        {"evidence_ids": ("different-evidence",)},
        {"claim_latch_receipt_id": None},
        {"claim_latch_receipt_id": "other-claim"},
        {"qa_report_id": None},
        {"qa_report_id": "other-qa"},
    ],
)
def test_saved_audit_references_cannot_disappear_or_change(tmp_path, changes: dict[str, object]) -> None:
    executions = ExecutionStore(_store(tmp_path))
    original = _envelope()
    executions.save(original)
    changed = ExecutionEnvelope.model_validate({**original.model_dump(), **changes})

    with pytest.raises(ValueError, match="audit|evidence|receipt|report"):
        executions.save(changed)
    assert executions.get("execution-1") == original


def test_new_evidence_may_be_appended_without_replacing_previous_refs(tmp_path) -> None:
    executions = ExecutionStore(_store(tmp_path))
    original = _envelope()
    executions.save(original)
    enriched = ExecutionEnvelope.model_validate(
        {**original.model_dump(), "evidence_ids": ("evidence-1", "evidence-2")}
    )

    executions.save(enriched)
    assert executions.get("execution-1").evidence_ids == ("evidence-1", "evidence-2")


def test_events_receive_durable_ordered_cursors_and_replay_by_project_revision(tmp_path) -> None:
    store = _store(tmp_path)
    executions = ExecutionStore(store)
    executions.save(_envelope())
    first = executions.append_event(_event())
    second = executions.append_event(_event())
    assert (first.cursor, second.cursor) == (1, 2)

    reopened = ExecutionStore(SQLiteStore(store.path))
    assert [item.cursor for item in reopened.replay_events(project_id="project-1", revision="rev-1")] == [1, 2]
    assert [item.cursor for item in reopened.replay_events(after_cursor=1)] == [2]
    assert reopened.replay_events(project_id="project-1", revision="rev-2") == []


def _manifest(plugin_id: str = "echo") -> dict[str, object]:
    return {
        "id": plugin_id,
        "version": "1.2.3",
        "displayName": "Echo",
        "capabilities": ["echo"],
        "permissions": ["local.read"],
    }


def test_plugin_registration_round_trip_status_and_manifest_version(tmp_path) -> None:
    store = _store(tmp_path)
    registrations = PluginRegistrationStore(store)
    created = registrations.register(_manifest())
    assert created.plugin_id == "echo"
    assert created.status == "available"
    assert created.manifest["version"] == "1.2.3"
    assert created.created_at <= created.updated_at

    connected = registrations.set_status("echo", "connected")
    reopened = PluginRegistrationStore(SQLiteStore(store.path))
    assert reopened.get("echo").status == "connected"
    assert reopened.get("echo").manifest == _manifest()
    assert reopened.get("echo").created_at == created.created_at
    assert connected.updated_at >= created.updated_at
    assert [entry.plugin_id for entry in reopened.list(status="connected")] == ["echo"]
    assert reopened.list(status="available") == []


def test_plugin_removal_disables_listing_and_retains_audit_history(tmp_path) -> None:
    store = _store(tmp_path)
    registrations = PluginRegistrationStore(store)
    registrations.register(_manifest())
    registrations.set_status("echo", "failed")
    registrations.remove("echo")

    reopened = PluginRegistrationStore(SQLiteStore(store.path))
    assert reopened.list() == []
    with pytest.raises(KeyError, match="Plugin"):
        reopened.get("echo")
    with sqlite3.connect(store.path) as connection:
        registration = connection.execute(
            "SELECT status, removed_at, manifest_json FROM plugin_registrations WHERE plugin_id = 'echo'"
        ).fetchone()
        actions = [row[0] for row in connection.execute(
            "SELECT action FROM plugin_audit_events WHERE plugin_id = 'echo' ORDER BY id"
        )]
    assert registration[0] == "removed"
    assert registration[1] is not None
    assert '"version": "1.2.3"' in registration[2]
    assert actions == ["registered", "status:failed", "removed"]


def test_plugin_registration_rejects_duplicate_and_invalid_status(tmp_path) -> None:
    registrations = PluginRegistrationStore(_store(tmp_path))
    registrations.register(_manifest())
    with pytest.raises(ValueError, match="already|registered"):
        registrations.register(_manifest())
    with pytest.raises(ValueError, match="status"):
        registrations.set_status("echo", "made_up")
    assert registrations.get("echo").status == "available"


def test_runtime_tables_are_added_without_discarding_existing_project_data(tmp_path) -> None:
    store = _store(tmp_path)
    store.init()
    with sqlite3.connect(store.path) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert store.get_project("project-1").name == "Todo"
    assert {
        "execution_envelopes", "execution_events", "plugin_registrations", "plugin_audit_events"
    } <= names
