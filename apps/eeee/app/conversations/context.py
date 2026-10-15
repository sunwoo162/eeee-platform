from __future__ import annotations

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
        selected: list[dict[str, str]] = []
        if memory_ids and self.memory_store is not None:
            for memory_id in memory_ids:
                try:
                    memory = self.memory_store.get(memory_id)
                except KeyError:
                    continue
                if memory.status is not MemoryStatus.ACTIVE:
                    continue
                selected.append({
                    "role": "system",
                    "content": f"Approved memory [{memory.id}]: {memory.content}",
                })
        used = 0
        for message in reversed(self.store.get_messages(conversation_id, limit=500)):
            item = {"role": message.role.value, "content": message.content}
            size = len(message.content)
            if selected and used + size > max_characters:
                break
            selected.append(item)
            used += size
        conversation_messages = list(reversed(selected))
        # Explicit memories stay ahead of transcript messages; they are never
        # discovered implicitly from raw conversation text.
        explicit = [item for item in selected if item["role"] == "system"]
        transcript = [item for item in conversation_messages if item["role"] != "system"]
        return explicit + transcript
