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


def test_route_turn_creates_canonical_conversation_and_updates_background_reply(tmp_path) -> None:
    conversations = make_store(tmp_path)

    first_user, first_assistant = conversations.record_route_turn(
        "desktop-default",
        user_content="프로젝트를 시작해줘",
        assistant_content="백그라운드에서 시작했어.",
        request_id="route-1",
        assistant_status=MessageStatus.PENDING,
    )
    second_user, second_assistant = conversations.record_route_turn(
        "desktop-default",
        user_content="프로젝트를 시작해줘",
        assistant_content="완료 결과와 검증을 확인했어.",
        request_id="route-1",
    )

    assert first_user.id == second_user.id
    assert first_assistant.id == second_assistant.id
    messages = conversations.get_messages("desktop-default")
    assert len(messages) == 2
    assert messages[1].content == "완료 결과와 검증을 확인했어."
    assert messages[1].status is MessageStatus.COMPLETED

    summaries = conversations.list_transcript_summaries(query="검증")
    assert summaries[0]["conversationId"] == "desktop-default"
    transcript = conversations.get_transcript("desktop-default")
    assert [turn["role"] for turn in transcript["turns"]] == ["user", "assistant"]
    assert transcript["turns"][1]["messageId"] == second_assistant.id


def test_route_lifecycle_reopens_a_failed_request_for_a_new_attempt(tmp_path) -> None:
    conversations = make_store(tmp_path)
    conversations.record_route_turn(
        "desktop-default",
        user_content="프로젝트를 다시 실행해줘",
        assistant_content="실패했어.",
        request_id="route-retry-1",
        assistant_status=MessageStatus.FAILED,
        error_code="assistant_route_failed",
    )

    conversations.record_route_lifecycle(
        "desktop-default", "route-retry-1", "failed", error_code="assistant_route_failed"
    )
    retried = conversations.record_route_lifecycle(
        "desktop-default", "route-retry-1", "accepted"
    )

    assert retried is not None
    assert retried.state is RequestState.EXECUTING
    assert retried.attempt == 2
    events = conversations.events_after("route-retry-1")
    assert events[-2].event_type == "request.retry"
    assert events[-1].event_type == "request.executing"


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


def test_duplicate_request_client_message_is_idempotent(tmp_path) -> None:
    conversations = make_store(tmp_path)
    conversation = conversations.create_conversation()
    user = conversations.add_message(
        conversation.id,
        role=MessageRole.USER,
        content="요청 중복 방지",
        status=MessageStatus.COMPLETED,
        client_message_id="same-request-id",
    )

    first = conversations.create_request(
        conversation.id, user.id, "same-request-id"
    )
    second = conversations.create_request(
        conversation.id, user.id, "same-request-id"
    )

    assert second.id == first.id
    assert conversations.find_request_by_client_message(
        conversation.id, "same-request-id"
    ).id == first.id


def test_transcript_summary_listing_pages_with_a_stable_keyset_cursor(tmp_path) -> None:
    conversations = make_store(tmp_path)
    for index in range(1, 5):
        conversation_id = f"conversation-{index}"
        conversations.record_route_turn(
            conversation_id,
            user_content=f"페이지 {index} 공통 검색어",
            assistant_content=f"답변 {index}",
            request_id=f"request-{index}",
        )

    # Force a timestamp tie so the conversation id must be the second cursor key.
    with conversations.store._connect() as connection:
        connection.execute(
            "UPDATE conversations SET updated_at = ?",
            ("2026-10-21T00:00:00+00:00",),
        )

    first_page = conversations.list_transcript_summaries(query="공통", limit=2)
    cursor = (first_page[-1]["updatedAt"], first_page[-1]["conversationId"])
    second_page = conversations.list_transcript_summaries(
        query="공통",
        limit=2,
        before_updated_at=cursor[0],
        before_conversation_id=cursor[1],
    )

    assert [item["conversationId"] for item in first_page] == [
        "conversation-4", "conversation-3"
    ]
    assert [item["conversationId"] for item in second_page] == [
        "conversation-2", "conversation-1"
    ]
