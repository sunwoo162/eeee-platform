from app.conversations.models import MessageRole, MessageStatus, RequestState
from app.conversations.store import ConversationStore
from app.storage.sqlite import SQLiteStore


def make_store(tmp_path) -> ConversationStore:
    durable = SQLiteStore(tmp_path / "state.sqlite3")
    durable.init()
    return ConversationStore(durable)


def test_conversation_messages_have_stable_sequence_and_survive_restart(tmp_path) -> None:
    conversations = make_store(tmp_path)
    conversation = conversations.create_conversation("첫 대화")
    user = conversations.add_message(
        conversation.id,
        role=MessageRole.USER,
        content="안녕",
        status=MessageStatus.COMPLETED,
        client_message_id="client-1",
    )
    assistant = conversations.add_message(
        conversation.id,
        role=MessageRole.ASSISTANT,
        content="안녕하세요.",
        status=MessageStatus.COMPLETED,
        request_id="request-1",
    )

    restarted = make_store(tmp_path)
    messages = restarted.get_messages(conversation.id)

    assert [item.id for item in messages] == [user.id, assistant.id]
    assert [item.sequence for item in messages] == [1, 2]
    assert [item.role for item in messages] == ["user", "assistant"]


def test_duplicate_client_message_is_idempotent(tmp_path) -> None:
    conversations = make_store(tmp_path)
    conversation = conversations.create_conversation()

    first = conversations.add_message(
        conversation.id,
        role=MessageRole.USER,
        content="중복 방지",
        status=MessageStatus.COMPLETED,
        client_message_id="same-client-id",
    )
    second = conversations.add_message(
        conversation.id,
        role=MessageRole.USER,
        content="중복 방지",
        status=MessageStatus.COMPLETED,
        client_message_id="same-client-id",
    )

    assert second.id == first.id
    assert len(conversations.get_messages(conversation.id)) == 1


def test_request_events_are_cursor_ordered(tmp_path) -> None:
    conversations = make_store(tmp_path)
    conversation = conversations.create_conversation()
    user = conversations.add_message(
        conversation.id,
        role=MessageRole.USER,
        content="상태를 저장해",
        status=MessageStatus.COMPLETED,
        client_message_id="client-1",
    )
    request = conversations.create_request(conversation.id, user.id, "client-1")
    conversations.transition_request(request.id, RequestState.PERSISTED_USER_MESSAGE)
    conversations.transition_request(request.id, RequestState.CLASSIFIED)
    conversations.append_event(request.id, "request.classified", {"status": "classified"})
    conversations.append_event(request.id, "message.started", {"messageId": "assistant-1"})

    events = conversations.events_after(request.id, after_sequence=0)

    assert [event.sequence for event in events] == [1, 2]
    assert [event.event_type for event in events] == ["request.classified", "message.started"]
