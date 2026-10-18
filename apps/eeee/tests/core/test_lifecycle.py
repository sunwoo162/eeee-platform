from pathlib import Path

import pytest

from app.conversations.context import ConversationContextBuilder
from app.conversations.service import ConversationService, CoreShuttingDownError
from app.conversations.store import ConversationStore
from app.core.lifecycle import CoreLifecycle, CoreLifecycleState
from app.core.lock import CoreAlreadyRunningError, ProcessLock
from app.storage.sqlite import SQLiteStore


class EmptyProvider:
    def stream(self, messages, *, cancel_event=None):
        yield "응답"


def _service(tmp_path: Path) -> tuple[ConversationService, SQLiteStore]:
    sqlite_store = SQLiteStore(tmp_path / "state.sqlite3")
    sqlite_store.init()
    conversations = ConversationStore(sqlite_store)
    service = ConversationService(
        conversations,
        provider=EmptyProvider(),
        context_builder=ConversationContextBuilder(conversations),
    )
    return service, sqlite_store


def test_lifecycle_acquires_lock_and_releases_it(tmp_path: Path) -> None:
    service, sqlite_store = _service(tmp_path)
    lifecycle = CoreLifecycle(
        sqlite_store,
        service,
        lock=ProcessLock(tmp_path / "core.lock"),
    )

    lifecycle.start()
    assert lifecycle.state == CoreLifecycleState.RUNNING
    assert lifecycle.accepting_requests is True

    lifecycle.stop()
    assert lifecycle.state == CoreLifecycleState.STOPPED
    assert lifecycle.accepting_requests is False


def test_lifecycle_rejects_second_owner(tmp_path: Path) -> None:
    service, sqlite_store = _service(tmp_path)
    first = CoreLifecycle(
        sqlite_store,
        service,
        lock=ProcessLock(tmp_path / "core.lock"),
    )
    second = CoreLifecycle(
        sqlite_store,
        service,
        lock=ProcessLock(tmp_path / "core.lock"),
    )
    first.start()
    try:
        with pytest.raises(CoreAlreadyRunningError):
            second.start()
        assert second.state == CoreLifecycleState.STOPPED
    finally:
        first.stop()


def test_stopping_lifecycle_rejects_new_turns(tmp_path: Path) -> None:
    service, sqlite_store = _service(tmp_path)
    lifecycle = CoreLifecycle(
        sqlite_store,
        service,
        lock=ProcessLock(tmp_path / "core.lock"),
    )
    lifecycle.start()
    lifecycle.stop()

    conversation = service.store.create_conversation()
    with pytest.raises(CoreShuttingDownError):
        service.prepare_turn(
            conversation.id,
            content="새 요청",
            client_message_id="client-shutdown",
        )
