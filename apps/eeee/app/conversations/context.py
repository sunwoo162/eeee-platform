from __future__ import annotations

from datetime import datetime, timezone

from app.conversations.store import ConversationStore
from app.memory.models import MemoryStatus
from app.memory.store import MemoryStore


class ConversationContextBuilder:
    def __init__(
        self,
        store: ConversationStore,
        *,
        memory_store: MemoryStore | None = None,
        max_context_tokens: int = 8192,
    ) -> None:
        if max_context_tokens <= 0:
            raise ValueError("max_context_tokens must be positive")
        self.store = store
        self.memory_store = memory_store
        self.max_context_tokens = max_context_tokens

    def build(
        self, conversation_id: str, *, memory_ids: list[str] | None = None
    ) -> list[dict[str, str]]:
        # A conservative character budget keeps the provider context bounded
        # without requiring a tokenizer in the Core package.
        max_characters = self.max_context_tokens * 4
        memory_items: list[dict[str, str]] = []
        if self.memory_store is not None:
            if memory_ids:
                memories = []
                for memory_id in memory_ids:
                    try:
                        memories.append(self.memory_store.get(memory_id))
                    except KeyError:
                        continue
            else:
                memories = self.memory_store.search("", limit=12)
            memory_budget = max_characters // 2
            memory_used = 0
            for memory in memories:
                if not _is_usable_memory(memory, conversation_id, automatic=not memory_ids):
                    continue
                item = {
                    "role": "system",
                    "content": f"Approved memory: {memory.content}",
                }
                size = len(item["content"])
                if size > max_characters:
                    continue
                # A single long approved memory may consume the reserved
                # transcript budget; dropping it would make an explicit user
                # correction silently ineffective. Keep it when it fits alone.
                if memory_used == 0 and size > memory_budget:
                    memory_items.append(item)
                    memory_used = size
                    break
                if memory_used + size > memory_budget:
                    continue
                memory_items.append(item)
                memory_used += size

        transcript: list[dict[str, str]] = []
        used = sum(len(item["content"]) for item in memory_items)
        for message in reversed(self.store.get_messages(conversation_id, limit=500)):
            item = {"role": message.role.value, "content": message.content}
            size = len(message.content)
            if size > max_characters - used:
                break
            transcript.append(item)
            used += size
        # Memories are only sourced from active records. Raw conversation turns
        # remain transcript context and are never promoted implicitly.
        return memory_items + list(reversed(transcript))


def _is_usable_memory(memory, conversation_id: str, *, automatic: bool) -> bool:
    if memory.status is not MemoryStatus.ACTIVE:
        return False
    if memory.expires_at is not None:
        expires_at = memory.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return False
    if automatic:
        scoped_conversation = memory.scope.get("conversationId")
        if scoped_conversation is not None and scoped_conversation != conversation_id:
            return False
    return True
