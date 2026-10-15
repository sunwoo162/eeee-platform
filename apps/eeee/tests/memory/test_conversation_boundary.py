from pathlib import Path

from app.conversations.context import ConversationContextBuilder
from app.conversations.models import MessageRole, MessageStatus
from app.conversations.store import ConversationStore
from app.memory.models import MemoryStatus
from app.memory.store import MemoryStore
from app.storage.sqlite import SQLiteStore


def test_conversation_is_not_memory_without_explicit_memory_ids(tmp_path: Path) -> None:
    sqlite_store = SQLiteStore(tmp_path / "state.sqlite3")
    sqlite_store.init()
    conversations = ConversationStore(sqlite_store)
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    memory.init()
    conversation = conversations.create_conversation()
    message = conversations.add_message(
        conversation.id,
        role=MessageRole.USER,
        content="이 내용은 자동 기억이 아니야",
        status=MessageStatus.COMPLETED,
        client_message_id="client-1",
    )
    saved = memory.save_explicit_memory(
        "사용자가 명시적으로 저장한 규칙",
        source_message_id=message.id,
        actor="user",
    )
    builder = ConversationContextBuilder(conversations, memory_store=memory)

    plain_context = builder.build(conversation.id)
    memory_context = builder.build(conversation.id, memory_ids=[saved.id])

    assert all(saved.content not in item["content"] for item in plain_context)
    assert any(saved.content in item["content"] for item in memory_context)


def test_explicit_memory_keeps_provenance_and_supports_edit_and_revoke(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    memory.init()

    saved = memory.save_explicit_memory(
        "처음 내용",
        source_message_id="message-1",
        actor="user",
    )
    edited = memory.edit(saved.id, "수정된 내용", actor="user")
    revoked = memory.revoke(saved.id, reason="사용자가 삭제함")

    assert edited.content == "수정된 내용"
    assert edited.source_type == "conversation"
    assert edited.source_message_id == "message-1"
    assert revoked.status is MemoryStatus.REVOKED
    assert memory.search("수정된") == []
