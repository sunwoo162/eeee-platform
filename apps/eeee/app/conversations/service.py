from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Protocol
from uuid import uuid4

from app.conversations.context import ConversationContextBuilder
from app.conversations.models import (
    AssistantEvent,
    AssistantRequest,
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
        self._cancel_events: dict[str, threading.Event] = {}
        self._accepting = True

    def set_accepting(self, accepting: bool) -> None:
        self._accepting = accepting

    def shutdown(self) -> None:
        self._accepting = False
        for request_id in list(self._cancel_events):
            try:
                self.cancel_request(request_id)
            except (KeyError, ValueError):
                continue

    def prepare_turn(
        self,
        conversation_id: str,
        *,
        content: str,
        client_message_id: str,
        parent_request_id: str | None = None,
        attempt: int = 1,
        user_message_id: str | None = None,
    ) -> tuple[AssistantRequest, bool]:
        existing = self.store.find_request_by_client_message(
            conversation_id, client_message_id
        )
        if existing is not None:
            return existing, False
        if not self._accepting:
            raise CoreShuttingDownError()
        if user_message_id is None:
            user_message = self.store.add_message(
                conversation_id,
                role=MessageRole.USER,
                content=content,
                status=MessageStatus.COMPLETED,
                client_message_id=client_message_id,
            )
            user_message_id = user_message.id
        request, request_created = self.store.create_request_with_status(
            conversation_id,
            user_message_id,
            client_message_id,
            parent_request_id=parent_request_id,
            attempt=attempt,
        )
        if not request_created:
            return request, False
        self._cancel_events[request.id] = threading.Event()
        self.store.append_event(request.id, "request.accepted", {"requestId": request.id})
        request = self.store.transition_request(
            request.id, RequestState.PERSISTED_USER_MESSAGE
        )
        return request, True

    def stream_turn(
        self,
        conversation_id: str,
        *,
        content: str,
        client_message_id: str,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[AssistantEvent]:
        request, created = self.prepare_turn(
            conversation_id,
            content=content,
            client_message_id=client_message_id,
        )
        if not created:
            yield from self.store.events_after(request.id)
            return
        if cancel_event is not None:
            self._cancel_events[request.id] = cancel_event
        accepted = self.store.events_after(request.id, limit=1)
        if accepted:
            yield accepted[0]
        yield from self.run_request(request.id)

    def run_request(self, request_id: str) -> Iterator[AssistantEvent]:
        request = self.store.get_request(request_id)
        terminal_states = {
            RequestState.COMPLETED,
            RequestState.FAILED,
            RequestState.CANCELLED,
            RequestState.INTERRUPTED,
        }
        if request.state in terminal_states:
            yield from self.store.events_after(request.id)
            return

        conversation_id = request.conversation_id
        request = self.store.transition_request(request.id, RequestState.CLASSIFIED)
        yield self.store.append_event(
            request.id, "request.classified", {"status": request.state.value}
        )
        request = self.store.transition_request(request.id, RequestState.GENERATING)
        assistant = None
        collected = ""
        cancel_event = self._cancel_events.setdefault(request.id, threading.Event())
        try:
            messages = self.context_builder.build(conversation_id)
            for delta in self.provider.stream(messages, cancel_event=cancel_event):
                if cancel_event.is_set():
                    raise ConversationCancelled()
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
                    request = self.store.transition_request(
                        request.id, RequestState.STREAMING
                    )
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
                request = self.store.transition_request(
                    request.id, RequestState.STREAMING
                )
            if cancel_event.is_set():
                raise ConversationCancelled()
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
            cancelled = error_code in {"conversation_cancelled", "ollama_cancelled"}
            if assistant is None:
                assistant = self.store.add_message(
                    conversation_id,
                    role=MessageRole.ASSISTANT,
                    content="",
                    status=MessageStatus.CANCELLED if cancelled else MessageStatus.FAILED,
                    request_id=request.id,
                    error_code=error_code,
                )
            else:
                self.store.update_message(
                    assistant.id,
                    content=collected,
                    status=MessageStatus.CANCELLED if cancelled else MessageStatus.FAILED,
                    error_code=error_code,
                )
            current = self.store.get_request(request.id)
            if current.state not in terminal_states:
                target = RequestState.CANCELLED if cancelled else RequestState.FAILED
                self.store.transition_request(
                    request.id, target, error_code=error_code
                )
            yield self.store.append_event(
                request.id,
                "request.cancelled" if cancelled else "request.failed",
                {
                    "messageId": assistant.id,
                    "errorCode": error_code,
                    "message": str(exc),
                },
            )
        finally:
            self._cancel_events.pop(request.id, None)

    def consume_request(self, request_id: str) -> None:
        for _event in self.run_request(request_id):
            pass

    def cancel_request(self, request_id: str) -> AssistantRequest:
        request = self.store.get_request(request_id)
        cancel_event = self._cancel_events.setdefault(request_id, threading.Event())
        cancel_event.set()
        if request.state in {
            RequestState.RECEIVED,
            RequestState.PERSISTED_USER_MESSAGE,
            RequestState.CLASSIFIED,
            RequestState.GENERATING,
            RequestState.STREAMING,
            RequestState.EXECUTING,
        }:
            request = self.store.transition_request(request_id, RequestState.CANCELLED)
            self.store.append_event(
                request_id, "request.cancelled", {"requestId": request_id}
            )
        return request

    def retry_request(self, request_id: str) -> AssistantRequest:
        original = self.store.get_request(request_id)
        if original.state not in {RequestState.FAILED, RequestState.INTERRUPTED}:
            raise ValueError("Only failed or interrupted requests can be retried")
        user_message = self.store.get_message(original.user_message_id)
        retry_client_id = f"retry-{uuid4().hex}"
        request, _created = self.prepare_turn(
            original.conversation_id,
            content=user_message.content,
            client_message_id=retry_client_id,
            parent_request_id=original.id,
            attempt=original.attempt + 1,
            user_message_id=original.user_message_id,
        )
        return request


class ConversationCancelled(RuntimeError):
    code = "conversation_cancelled"

    def __init__(self) -> None:
        super().__init__("Conversation request was cancelled")


class CoreShuttingDownError(RuntimeError):
    code = "core_shutting_down"

    def __init__(self) -> None:
        super().__init__("EEEE Core is shutting down")
