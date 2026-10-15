from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Protocol

from app.conversations.context import ConversationContextBuilder
from app.conversations.models import (
    AssistantEvent,
    MessageRole,
    MessageStatus,
    RequestState,
)
from app.conversations.store import ConversationStore


class ConversationProvider(Protocol):
    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[str]:
        """Yield assistant text deltas or raise a typed provider error."""


class ConversationService:
    def __init__(
        self,
        store: ConversationStore,
        *,
        provider: ConversationProvider,
        context_builder: ConversationContextBuilder | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.context_builder = context_builder or ConversationContextBuilder(store)

    def stream_turn(
        self,
        conversation_id: str,
        *,
        content: str,
        client_message_id: str,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[AssistantEvent]:
        user_message = self.store.add_message(
            conversation_id,
            role=MessageRole.USER,
            content=content,
            status=MessageStatus.COMPLETED,
            client_message_id=client_message_id,
        )
        request = self.store.create_request(conversation_id, user_message.id, client_message_id)
        yield self.store.append_event(request.id, "request.accepted", {"requestId": request.id})
        request = self.store.transition_request(request.id, RequestState.PERSISTED_USER_MESSAGE)
        request = self.store.transition_request(request.id, RequestState.CLASSIFIED)
        yield self.store.append_event(request.id, "request.classified", {"status": request.state.value})
        request = self.store.transition_request(request.id, RequestState.GENERATING)
        assistant = None
        collected = ""
        try:
            messages = self.context_builder.build(conversation_id)
            for delta in self.provider.stream(messages, cancel_event=cancel_event):
                if assistant is None:
                    assistant = self.store.add_message(
                        conversation_id,
                        role=MessageRole.ASSISTANT,
                        content="",
                        status=MessageStatus.STREAMING,
                        request_id=request.id,
                    )
                    yield self.store.append_event(
                        request.id, "message.started", {"messageId": assistant.id}
                    )
                    request = self.store.transition_request(request.id, RequestState.STREAMING)
                collected += delta
                self.store.update_message(
                    assistant.id,
                    content=collected,
                    status=MessageStatus.STREAMING,
                )
                yield self.store.append_event(
                    request.id,
                    "message.delta",
                    {"messageId": assistant.id, "delta": delta},
                )
            if assistant is None:
                assistant = self.store.add_message(
                    conversation_id,
                    role=MessageRole.ASSISTANT,
                    content="",
                    status=MessageStatus.STREAMING,
                    request_id=request.id,
                )
                yield self.store.append_event(
                    request.id, "message.started", {"messageId": assistant.id}
                )
                request = self.store.transition_request(request.id, RequestState.STREAMING)
            self.store.update_message(
                assistant.id,
                content=collected,
                status=MessageStatus.COMPLETED,
            )
            request = self.store.transition_request(request.id, RequestState.COMPLETED)
            yield self.store.append_event(
                request.id,
                "message.completed",
                {"messageId": assistant.id, "content": collected},
            )
        except Exception as exc:
            error_code = getattr(exc, "code", "conversation_failed")
            if assistant is None:
                assistant = self.store.add_message(
                    conversation_id,
                    role=MessageRole.ASSISTANT,
                    content="",
                    status=MessageStatus.FAILED,
                    request_id=request.id,
                    error_code=error_code,
                )
            else:
                self.store.update_message(
                    assistant.id,
                    content=collected,
                    status=MessageStatus.FAILED,
                    error_code=error_code,
                )
            self.store.transition_request(request.id, RequestState.FAILED, error_code=error_code)
            yield self.store.append_event(
                request.id,
                "request.failed",
                {"messageId": assistant.id, "errorCode": error_code, "message": str(exc)},
            )
