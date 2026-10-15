from __future__ import annotations

from app.conversations.store import ConversationStore


def recover_interrupted(store: ConversationStore) -> list[str]:
    """Mark work that could not survive a Core process exit as interrupted."""

    return store.recover_interrupted()
