from __future__ import annotations

from app.conversations.store import ConversationStore


class ConversationContextBuilder:
    def __init__(self, store: ConversationStore, *, max_context_tokens: int = 8192) -> None:
        if max_context_tokens <= 0:
            raise ValueError("max_context_tokens must be positive")
        self.store = store
        self.max_context_tokens = max_context_tokens

    def build(self, conversation_id: str) -> list[dict[str, str]]:
        # A conservative character budget keeps the provider context bounded
        # without requiring a tokenizer in the Core package.
        max_characters = self.max_context_tokens * 4
        selected: list[dict[str, str]] = []
        used = 0
        for message in reversed(self.store.get_messages(conversation_id, limit=500)):
            item = {"role": message.role.value, "content": message.content}
            size = len(message.content)
            if selected and used + size > max_characters:
                break
            selected.append(item)
            used += size
        selected.reverse()
        return selected
