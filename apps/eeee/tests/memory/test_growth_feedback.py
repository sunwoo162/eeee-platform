from pathlib import Path

import pytest

from app.assistant.growth import GrowthFeedbackError, GrowthService
from app.memory.models import MemoryStatus
from app.memory.store import MemoryStore


def _service(tmp_path: Path) -> tuple[GrowthService, MemoryStore]:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.init()
    return GrowthService(store), store


def test_feedback_is_persistent_but_not_active_memory_without_explicit_remember(tmp_path: Path) -> None:
    service, store = _service(tmp_path)

    feedback = service.record_feedback(
        client_feedback_id="feedback-1",
        conversation_id="conversation-1",
        message_id="message-1",
        rating="negative",
        correction="답변은 먼저 결론부터 짧게 말해줘.",
        remember=False,
    )

    assert feedback.id == "feedback-1"
    assert feedback.memory_id is None
    assert store.list_records(status=MemoryStatus.ACTIVE) == []
    reopened = MemoryStore(tmp_path / "memory.sqlite3")
    reopened.init()
    assert reopened.get_feedback("feedback-1").correction == "답변은 먼저 결론부터 짧게 말해줘."


def test_explicit_remember_promotes_feedback_into_editable_memory(tmp_path: Path) -> None:
    service, store = _service(tmp_path)

    feedback = service.record_feedback(
        client_feedback_id="feedback-remember",
        conversation_id="conversation-1",
        request_id="request-1",
        message_id="message-1",
        rating="negative",
        correction="사용자는 답변을 한국어로 간결하게 받기를 원함.",
        remember=True,
    )

    assert feedback.memory_id
    memory = store.get(feedback.memory_id)
    assert memory.status is MemoryStatus.ACTIVE
    assert memory.user_editable is True
    assert feedback.id in memory.evidence_ids
    assert memory.source_message_id == "message-1"


def test_remember_requires_correction_and_does_not_leave_partial_feedback(tmp_path: Path) -> None:
    service, store = _service(tmp_path)

    with pytest.raises(GrowthFeedbackError, match="correction"):
        service.record_feedback(
            client_feedback_id="feedback-invalid",
            conversation_id="conversation-1",
            message_id="message-1",
            rating="positive",
            correction=None,
            remember=True,
        )

    with pytest.raises(KeyError):
        store.get_feedback("feedback-invalid")


def test_duplicate_feedback_is_idempotent(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    kwargs = {
        "client_feedback_id": "feedback-duplicate",
        "conversation_id": "conversation-1",
        "message_id": "message-1",
        "rating": "negative",
        "correction": "짧게 답해줘.",
        "remember": True,
    }

    first = service.record_feedback(**kwargs)
    second = service.record_feedback(**kwargs)

    assert second == first
    assert len(store.list_records(status=MemoryStatus.ACTIVE)) == 1


def test_feedback_and_promoted_memory_redact_common_credentials(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    secret_text = (
        'Authorization: Bearer bearer-secret cookie=session-secret '
        '"api_key": "json-secret" eyJhbGciOiJIUzI1NiJ9.payload.signature'
    )

    feedback = service.record_feedback(
        client_feedback_id="feedback-secret",
        conversation_id="conversation-1",
        message_id="message-1",
        rating="negative",
        correction=secret_text,
        remember=True,
    )

    stored_feedback = store.get_feedback(feedback.id)
    stored_memory = store.get(feedback.memory_id)
    for stored in (stored_feedback.correction or "", stored_memory.content):
        assert "bearer-secret" not in stored
        assert "session-secret" not in stored
        assert "json-secret" not in stored
        assert "eyJhbGciOiJIUzI1NiJ9.payload.signature" not in stored


def test_feedback_promotion_is_retry_safe_after_existing_feedback_row(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    kwargs = {
        "client_feedback_id": "feedback-retry",
        "conversation_id": "conversation-1",
        "message_id": "message-1",
        "rating": "negative",
        "correction": "재시도해도 기억은 하나만 만들어야 해.",
        "remember": True,
    }
    first = service.record_feedback(**kwargs)
    second = service.record_feedback(**kwargs)

    assert second.memory_id == first.memory_id
    assert len(store.list_records(status=MemoryStatus.ACTIVE)) == 1
