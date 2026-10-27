from __future__ import annotations

from datetime import UTC, datetime

from app.conversations.models import ConversationMessage, MessageRole, MessageStatus
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
        self.workspace_store = None
        self.max_context_tokens = max_context_tokens

    def build(
        self, conversation_id: str, *, memory_ids: list[str] | None = None,
        user_id: str = "local-user",
    ) -> list[dict[str, str]]:
        # A conservative character budget keeps the provider context bounded
        # without requiring a tokenizer in the Core package.
        max_characters = self.max_context_tokens * 4
        memory_items: list[dict[str, str]] = []
        project = (
            self.workspace_store.project_for_conversation(conversation_id, user_id=user_id)
            if self.workspace_store is not None else None
        )
        # Personal/global memories do not silently enter a team conversation.
        # Explicit sharing requires a separate, reviewable project memory note.
        team_project = project is not None and project.get("workspace_kind") == "team"
        if self.memory_store is not None and not team_project:
            if memory_ids:
                memories = []
                for memory_id in memory_ids:
                    try:
                        memories.append(self.memory_store.get(memory_id, user_id=user_id))
                    except KeyError:
                        continue
            else:
                memories = self.memory_store.search("", user_id=user_id, limit=12)
            memory_budget = max_characters // 2
            memory_used = 0
            for memory in memories:
                if not _is_usable_memory(
                    memory, conversation_id, project_id=(project or {}).get("id"),
                    automatic=not memory_ids,
                ):
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

        # Project membership, not chat title, determines which sibling chats and
        # reviewed project notes are visible. Reserve most of the context for
        # the active conversation so folders cannot drown out the user's turn.
        if self.workspace_store is not None:
            project_budget = max_characters // 4
            project_used = 0
            for item in self.workspace_store.context_items(
                conversation_id, user_id=user_id
            ):
                size = len(item["content"])
                if size + project_used > project_budget:
                    continue
                memory_items.append(item)
                project_used += size

        transcript: list[dict[str, str]] = []
        used = sum(len(item["content"]) for item in memory_items)
        for message in reversed(
            self.store.get_messages(conversation_id, limit=500, user_id=user_id)
        ):
            if not _is_usable_context_message(message):
                continue
            item = {"role": message.role.value, "content": message.content}
            size = len(message.content)
            if size > max_characters - used:
                break
            transcript.append(item)
            used += size
        # Memories are only sourced from active records. Raw conversation turns
        # remain transcript context and are never promoted implicitly.
        return memory_items + list(reversed(transcript))


def _is_usable_context_message(message: ConversationMessage) -> bool:
    """Return whether a persisted message is safe to send back to a provider.

    The transcript is the user-facing audit trail, so failed and interrupted
    assistant output must remain stored. It is not, however, a trustworthy
    conversational turn: a partial stream can contain invented or incomplete
    instructions and would cause the next request to build on a failed run.
    User, system, and tool messages keep their existing behavior. Pending
    assistant messages are intentional durable acknowledgements for queued
    work and remain useful context until a completed result replaces them.
    """

    if message.role is not MessageRole.ASSISTANT:
        return True
    return message.status in {MessageStatus.PENDING, MessageStatus.COMPLETED}


def _is_usable_memory(
    memory, conversation_id: str, *, project_id: str | None = None,
    automatic: bool,
) -> bool:
    if memory.status is not MemoryStatus.ACTIVE:
        return False
    if memory.expires_at is not None:
        expires_at = memory.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            return False
    # Project-scoped facts must not escape their project, even when explicitly
    # requested by memory ID. Unscoped project outcomes are excluded from
    # folder conversations until they are curated into that folder.
    declared_project = memory.scope.get("projectId") or memory.scope.get("project_id")
    if declared_project is not None and declared_project != project_id:
        return False
    if project_id is not None and declared_project is None and memory.kind != "user_preference":
        return False
    if automatic:
        scoped_conversation = memory.scope.get("conversationId")
        if scoped_conversation is not None and scoped_conversation != conversation_id:
            return False
    return True
