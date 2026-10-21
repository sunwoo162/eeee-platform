from pathlib import Path

from app.conversations.context import ConversationContextBuilder
from app.conversations.models import MessageRole, MessageStatus
from app.conversations.store import ConversationStore
from app.storage.sqlite import SQLiteStore


def test_incomplete_assistant_output_is_not_reused_as_model_context(tmp_path: Path) -> None:
    sqlite_store = SQLiteStore(tmp_path / "state.sqlite3")
    sqlite_store.init()
    conversations = ConversationStore(sqlite_store)
    conversation = conversations.create_conversation()

    conversations.add_message(
        conversation.id,
        role=MessageRole.USER,
        content="실패한 요청을 다시 판단해줘.",
        status=MessageStatus.COMPLETED,
        client_message_id="client-user",
    )
    for status, suffix in (
        (MessageStatus.FAILED, "실패한 스트림"),
        (MessageStatus.CANCELLED, "취소된 스트림"),
        (MessageStatus.INTERRUPTED, "중단된 스트림"),
        (MessageStatus.STREAMING, "아직 생성 중인 스트림"),
    ):
        conversations.add_message(
            conversation.id,
            role=MessageRole.ASSISTANT,
            content=f"모델이 만들어낸 {suffix}",
            status=status,
            client_message_id=f"client-{suffix}",
        )
    conversations.add_message(
        conversation.id,
        role=MessageRole.ASSISTANT,
        content="검증된 정상 응답",
        status=MessageStatus.COMPLETED,
        client_message_id="client-completed",
    )

    context = ConversationContextBuilder(conversations).build(conversation.id)
    contents = [item["content"] for item in context]

    assert contents == ["실패한 요청을 다시 판단해줘.", "검증된 정상 응답"]
