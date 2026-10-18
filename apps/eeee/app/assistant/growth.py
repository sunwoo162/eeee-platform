from __future__ import annotations

from app.conversations.store import ConversationStore
from app.memory.models import GrowthFeedback, MemoryRecord
from app.memory.store import MemoryConflictError, MemoryStore


class GrowthFeedbackError(ValueError):
    """A feedback event cannot be accepted or promoted safely."""


class GrowthService:
    """Turn explicit user feedback into durable, user-editable assistant memory."""

    def __init__(
        self,
        memory: MemoryStore,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self.memory = memory
        self.conversation_store = conversation_store
        self.memory.init()

    def record_feedback(
        self,
        *,
        client_feedback_id: str,
        conversation_id: str,
        message_id: str,
        rating: str,
        correction: str | None = None,
        remember: bool = False,
        actor: str = "user",
        request_id: str | None = None,
    ) -> GrowthFeedback:
        if remember and (not isinstance(correction, str) or not correction.strip()):
            raise GrowthFeedbackError(
                "remember=true requires a non-empty correction"
            )
        self._validate_source(
            conversation_id=conversation_id,
            message_id=message_id,
        )
        try:
            if remember:
                return self.memory.save_feedback_with_memory(
                    feedback_id=client_feedback_id,
                    conversation_id=conversation_id,
                    request_id=request_id,
                    message_id=message_id,
                    rating=rating,
                    correction=correction or "",
                    actor=actor,
                )
            return self.memory.save_feedback(
                feedback_id=client_feedback_id,
                conversation_id=conversation_id,
                request_id=request_id,
                message_id=message_id,
                rating=rating,
                correction=correction,
                remember=False,
                actor=actor,
            )
        except GrowthFeedbackError:
            raise
        except (KeyError, MemoryConflictError, ValueError) as exc:
            raise GrowthFeedbackError(str(exc)) from exc

    def memory_for_feedback(self, feedback: GrowthFeedback) -> MemoryRecord | None:
        if feedback.memory_id is None:
            return None
        try:
            return self.memory.get(feedback.memory_id)
        except KeyError as exc:
            raise GrowthFeedbackError(
                f"Feedback {feedback.id} points to missing memory {feedback.memory_id}"
            ) from exc

    def _validate_source(self, *, conversation_id: str, message_id: str) -> None:
        if self.conversation_store is None:
            return
        try:
            conversation = self.conversation_store.get_conversation(conversation_id)
            message = self.conversation_store.get_message(message_id)
        except KeyError as exc:
            raise GrowthFeedbackError("feedback source conversation or message was not found") from exc
        if message.conversation_id != conversation.id:
            raise GrowthFeedbackError("feedback message does not belong to the conversation")
