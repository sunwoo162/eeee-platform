from pathlib import Path

from app.conversations.models import MessageRole, MessageStatus, RequestState
from app.conversations.store import ConversationStore
from app.core.recovery import recover_interrupted
from app.storage.sqlite import SQLiteStore


def test_recovery_marks_inflight_request_and_streaming_message_interrupted(
    tmp_path: Path,
) -> None:
    sqlite_store = SQLiteStore(tmp_path / "state.sqlite3")
    sqlite_store.init()
    conversations = ConversationStore(sqlite_store)
    conversation = conversations.create_conversation("복구 테스트")
    user_message = conversations.add_message(
        conversation.id,
        role=MessageRole.USER,
        content="계속 진행해",
        status=MessageStatus.COMPLETED,
        client_message_id="client-1",
    )
    request = conversations.create_request(
        conversation.id, user_message.id, "client-1"
    )
    conversations.transition_request(request.id, RequestState.PERSISTED_USER_MESSAGE)
    conversations.transition_request(request.id, RequestState.CLASSIFIED)
    conversations.transition_request(request.id, RequestState.GENERATING)
    assistant_message = conversations.add_message(
        conversation.id,
        role=MessageRole.ASSISTANT,
        content="아직 답변 중",
        status=MessageStatus.STREAMING,
        request_id=request.id,
    )

    recovered = recover_interrupted(conversations)

    assert recovered == [request.id]
    recovered_request = conversations.get_request(request.id)
    assert recovered_request.state == RequestState.INTERRUPTED
    assert recovered_request.error_code == "core_restarted"
    recovered_message = conversations.get_message(assistant_message.id)
    assert recovered_message.status == MessageStatus.INTERRUPTED
    assert recovered_message.error_code == "core_restarted"
    events = conversations.events_after(request.id)
    assert events[-1].event_type == "request.interrupted"
    assert events[-1].payload["reason"] == "core_restarted"


def test_recovery_ignores_terminal_requests(tmp_path: Path) -> None:
    sqlite_store = SQLiteStore(tmp_path / "state.sqlite3")
    sqlite_store.init()
    conversations = ConversationStore(sqlite_store)
    conversation = conversations.create_conversation()
    user_message = conversations.add_message(
        conversation.id,
        role=MessageRole.USER,
        content="끝난 작업",
        status=MessageStatus.COMPLETED,
        client_message_id="client-2",
    )
    request = conversations.create_request(
        conversation.id, user_message.id, "client-2"
    )
    conversations.transition_request(request.id, RequestState.PERSISTED_USER_MESSAGE)
    conversations.transition_request(request.id, RequestState.CLASSIFIED)
    conversations.transition_request(request.id, RequestState.GENERATING)
    conversations.transition_request(request.id, RequestState.FAILED, error_code="test")

    assert recover_interrupted(conversations) == []
    assert conversations.get_request(request.id).state == RequestState.FAILED
