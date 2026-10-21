from __future__ import annotations

from datetime import datetime, timezone

from app.assistant.registry import build_default_registry
from app.assistant.reminders import ReminderDraft, ReminderStore
from app.assistant.router import CapabilityRouter
from app.assistant.service import AssistantService
from app.config import Settings
from app.coordinator.service import Coordinator
from app.project_runtime.provisioner import ProjectProvisioner
from app.storage.sqlite import SQLiteStore


def _service(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    return AssistantService(
        router=CapabilityRouter(build_default_registry()),
        coordinator=Coordinator(store),
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
    )


def test_local_secretary_persists_and_lists_a_reminder(tmp_path) -> None:
    service = _service(tmp_path)

    created = service.route("내일 오후 3시에 팀 회의 알려줘")

    assert created.selection.capability_id == "personal-secretary"
    assert created.status == "completed"
    assert created.project_id is None
    assert created.plugin_output is None
    assert "팀 회의" in created.message
    assert created.reminder is not None
    assert created.reminder["title"] == "팀 회의"
    due_at = datetime.fromisoformat(created.reminder["dueAt"])
    assert due_at.tzinfo is not None
    assert due_at.hour == 15

    restarted = _service(tmp_path)
    listed = restarted.route("일정 보여줘")

    assert listed.status == "completed"
    assert listed.reminders
    assert listed.reminders[0]["title"] == "팀 회의"


def test_local_secretary_blocks_an_ambiguous_reminder_request(tmp_path) -> None:
    service = _service(tmp_path)

    result = service.route("회의 일정 등록해줘")

    assert result.status == "blocked"
    assert "언제" in result.message
    assert result.reminder is None


def test_local_secretary_does_not_save_a_statement_as_a_reminder(tmp_path) -> None:
    service = _service(tmp_path)

    result = service.route("내일 오후 3시에 회의가 있어")

    assert result.status == "blocked"
    assert result.reminder is None


def test_local_secretary_does_not_turn_a_schedule_question_into_a_write(tmp_path) -> None:
    service = _service(tmp_path)

    result = service.route("내일 오후 3시에 회의가 있는지 알려줘")

    assert result.status == "blocked"
    assert result.reminder is None


def test_local_secretary_does_not_save_a_time_question(tmp_path) -> None:
    service = _service(tmp_path)

    result = service.route("내일 오후 3시에 회의 시간 알려줘")

    assert result.status == "blocked"
    assert result.reminder is None


def test_reminder_store_is_idempotent_for_a_request_id(tmp_path) -> None:
    store = ReminderStore(tmp_path / "data" / "state.sqlite3")
    draft = ReminderDraft(
        title="팀 회의",
        due_at=datetime(2026, 10, 22, 15, tzinfo=timezone.utc),
    )

    first = store.create("conversation-1", draft, request_id="request-1")
    retry = store.create("conversation-1", draft, request_id="request-1")

    assert retry.id == first.id
    assert [item.id for item in store.list("conversation-1")] == [first.id]

