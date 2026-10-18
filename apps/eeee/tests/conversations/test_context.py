from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.conversations.context import ConversationContextBuilder
from app.conversations.models import MessageRole, MessageStatus
from app.conversations.store import ConversationStore
from app.memory.models import MemoryStatus
from app.memory.store import MemoryStore
from app.storage.sqlite import SQLiteStore


def _stores(tmp_path: Path) -> tuple[ConversationStore, MemoryStore]:
    sqlite_store = SQLiteStore(tmp_path / "state.sqlite3")
    sqlite_store.init()
    conversations = ConversationStore(sqlite_store)
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    memory.init()
    return conversations, memory


def test_active_memory_is_added_automatically_but_raw_turns_are_not(tmp_path: Path) -> None:
    conversations, memory = _stores(tmp_path)
    conversation = conversations.create_conversation()
    conversations.add_message(
        conversation.id,
        role=MessageRole.USER,
        content="이 문장은 대화 기록일 뿐이야.",
        status=MessageStatus.COMPLETED,
        client_message_id="client-1",
    )
    saved = memory.save_explicit_memory(
        "답변은 결론부터 간결하게 제시한다.",
        source_message_id="message-1",
        actor="user",
    )

    context = ConversationContextBuilder(conversations, memory_store=memory).build(
        conversation.id
    )

    assert any(saved.content in item["content"] for item in context)
    assert any("대화 기록일 뿐이야" in item["content"] for item in context)
    assert not any("Approved memory" in item["content"] and "대화 기록일 뿐이야" in item["content"] for item in context)


def test_revoked_and_superseded_memories_are_not_added(tmp_path: Path) -> None:
    conversations, memory = _stores(tmp_path)
    conversation = conversations.create_conversation()
    revoked = memory.save_explicit_memory(
        "폐기된 규칙", source_message_id="message-revoked", actor="user"
    )
    replacement = memory.save_explicit_memory(
        "현재 규칙", source_message_id="message-current", actor="user"
    )
    memory.revoke(revoked.id, reason="더 이상 사용하지 않음")
    superseded = memory.save_explicit_memory(
        "대체된 규칙", source_message_id="message-old", actor="user"
    )
    memory.supersede(superseded.id, replacement.id)

    context = ConversationContextBuilder(conversations, memory_store=memory).build(
        conversation.id
    )

    contents = [item["content"] for item in context]
    assert any(replacement.content in content for content in contents)
    assert not any(revoked.content in content for content in contents)
    assert not any(superseded.content in content for content in contents)


def test_memory_and_transcript_share_a_hard_character_budget(tmp_path: Path) -> None:
    conversations, memory = _stores(tmp_path)
    conversation = conversations.create_conversation()
    for index in range(4):
        conversations.add_message(
            conversation.id,
            role=MessageRole.USER if index % 2 == 0 else MessageRole.ASSISTANT,
            content=f"대화-{index}-" + ("x" * 18),
            status=MessageStatus.COMPLETED,
            client_message_id=f"client-{index}",
        )
    memory.save_explicit_memory(
        "사용자 선호 규칙-" + ("y" * 18),
        source_message_id="message-memory",
        actor="user",
    )

    context = ConversationContextBuilder(
        conversations,
        memory_store=memory,
        max_context_tokens=20,
    ).build(conversation.id)

    assert sum(len(item["content"]) for item in context) <= 80
    assert context[0]["role"] == "system"


def test_explicit_memory_ids_remain_authoritative(tmp_path: Path) -> None:
    conversations, memory = _stores(tmp_path)
    conversation = conversations.create_conversation()
    selected = memory.save_explicit_memory(
        "선택한 기억", source_message_id="message-selected", actor="user"
    )
    other = memory.save_explicit_memory(
        "자동으로 고르면 안 되는 다른 기억",
        source_message_id="message-other",
        actor="user",
    )

    context = ConversationContextBuilder(conversations, memory_store=memory).build(
        conversation.id, memory_ids=[selected.id]
    )

    contents = [item["content"] for item in context]
    assert any(selected.content in content for content in contents)
    assert not any(other.content in content for content in contents)


def test_automatic_context_does_not_cross_conversation_memory_scope(tmp_path: Path) -> None:
    conversations, memory = _stores(tmp_path)
    first = conversations.create_conversation()
    second = conversations.create_conversation()
    memory.save_explicit_memory(
        "첫 대화 전용 비밀 규칙",
        source_message_id="message-first",
        actor="user",
        scope={"conversationId": first.id},
    )
    memory.save_explicit_memory(
        "두 번째 대화 규칙",
        source_message_id="message-second",
        actor="user",
        scope={"conversationId": second.id},
    )

    context = ConversationContextBuilder(conversations, memory_store=memory).build(second.id)

    contents = [item["content"] for item in context]
    assert any("두 번째 대화 규칙" in content for content in contents)
    assert not any("첫 대화 전용 비밀 규칙" in content for content in contents)


def test_explicit_memory_ids_skip_expired_records(tmp_path: Path) -> None:
    conversations, memory = _stores(tmp_path)
    conversation = conversations.create_conversation()
    saved = memory.save_explicit_memory(
        "만료된 규칙", source_message_id="message-expired", actor="user"
    )
    with memory._connect() as connection:
        connection.execute(
            "UPDATE memory_records SET expires_at = ? WHERE id = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), saved.id),
        )

    context = ConversationContextBuilder(conversations, memory_store=memory).build(
        conversation.id, memory_ids=[saved.id]
    )

    assert not any("만료된 규칙" in item["content"] for item in context)
