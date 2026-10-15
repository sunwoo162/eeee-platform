from __future__ import annotations

from app.memory.models import GrowthFeedback, MemoryRecord
from app.memory.store import MemoryConflictError, MemoryStore


class GrowthFeedbackError(ValueError):
    """A feedback event cannot be accepted or promoted safely."""


class GrowthService:
    """Turn explicit user feedback into durable, user-editable assistant memory."""

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory
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
        try:
            feedback = self.memory.save_feedback(
                feedback_id=client_feedback_id,
                conversation_id=conversation_id,
                request_id=request_id,
                message_id=message_id,
                rating=rating,
                correction=correction,
                remember=remember,
                actor=actor,
            )
            if not remember or feedback.memory_id is not None:
                return feedback
            if feedback.correction is None:
                raise GrowthFeedbackError(
                    "remember=true requires a non-empty correction"
                )
            memory = self.memory.save_explicit_memory(
                feedback.correction,
                source_message_id=feedback.message_id,
                source_project_id=f"conversation:{feedback.conversation_id}",
                actor=feedback.actor,
                kind="agent_routing_hint",
                scope={
                    "conversationId": feedback.conversation_id,
                    "source": "feedback",
                },
                evidence_ids=[feedback.id],
                verification_ids=[feedback.id],
            )
            return self.memory.attach_feedback_memory(feedback.id, memory.id)
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
