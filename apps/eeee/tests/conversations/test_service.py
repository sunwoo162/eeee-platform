import pytest

from app.conversations.models import MessageStatus, RequestState
from app.conversations.service import ConversationService
from app.conversations.store import ConversationStore
from app.storage.sqlite import SQLiteStore


class FakeProvider:
    def __init__(self, chunks=None, error=None) -> None:
        self.chunks = list(chunks or [])
        self.error = error
        self.messages = None

    def stream(self, messages, *, cancel_event=None):
        self.messages = messages
        if self.error is not None:
            raise self.error
        yield from self.chunks


class UserAwareProvider(FakeProvider):
    def __init__(self, chunks=None) -> None:
        super().__init__(chunks)
        self.user_ids = []

    def stream(self, messages, *, cancel_event=None, user_id="local-user"):
        self.user_ids.append(user_id)
        yield from super().stream(messages, cancel_event=cancel_event)


class RequestAwareProvider(FakeProvider):
    def __init__(self, chunks=None) -> None:
        super().__init__(chunks)
        self.scopes = []

    def stream(
        self,
        messages,
        *,
        cancel_event=None,
        user_id="local-user",
        request_id=None,
        conversation_id=None,
    ):
        self.scopes.append(
            {
                "user_id": user_id,
                "request_id": request_id,
                "conversation_id": conversation_id,
            }
        )
        yield from super().stream(messages, cancel_event=cancel_event)


class LateCancelProvider(FakeProvider):
    def stream(self, messages, *, cancel_event=None, user_id="local-user"):
        if cancel_event is not None:
            cancel_event.set()
        yield "late response"


def make_service(tmp_path, provider):
    durable = SQLiteStore(tmp_path / "state.sqlite3")
    durable.init()
    store = ConversationStore(durable)
    return store, ConversationService(store, provider=provider)


def test_conversation_service_persists_and_streams_a_complete_turn(tmp_path) -> None:
    store, service = make_service(tmp_path, FakeProvider(["안녕", "하세요."]))
    conversation = store.create_conversation()

    events = list(
        service.stream_turn(
            conversation.id,
            content="인사해줘",
            client_message_id="client-1",
        )
    )

    request = store.get_request(events[-1].request_id)
    messages = store.get_messages(conversation.id)

    assert request.state == RequestState.COMPLETED
    assert [message.content for message in messages] == ["인사해줘", "안녕하세요."]
    assert messages[-1].status == MessageStatus.COMPLETED
    assert [event.event_type for event in events] == [
        "request.accepted",
        "request.classified",
        "message.started",
        "message.delta",
        "message.delta",
        "message.completed",
    ]


def test_conversation_service_persists_provider_failure_without_fake_success(tmp_path) -> None:
    from app.agent.ollama_runtime import OllamaRuntimeError

    store, service = make_service(
        tmp_path,
        FakeProvider(error=OllamaRuntimeError("ollama unavailable", code="ollama_unavailable")),
    )
    conversation = store.create_conversation()

    events = list(
        service.stream_turn(
            conversation.id,
            content="답해줘",
            client_message_id="client-1",
        )
    )

    request = store.get_request(events[-1].request_id)
    messages = store.get_messages(conversation.id)

    assert request.state == RequestState.FAILED
    assert request.error_code == "ollama_unavailable"
    assert messages[-1].role == "assistant"
    assert messages[-1].status == MessageStatus.FAILED
    assert not any(event.event_type == "message.completed" for event in events)


def test_conversation_service_rejects_empty_provider_response(tmp_path) -> None:
    store, service = make_service(tmp_path, FakeProvider())
    conversation = store.create_conversation()

    events = list(
        service.stream_turn(
            conversation.id,
            content="빈 답변이면 안 돼",
            client_message_id="client-empty",
        )
    )

    request = store.get_request(events[-1].request_id)
    messages = store.get_messages(conversation.id)

    assert request.state == RequestState.FAILED
    assert request.error_code == "provider_empty_response"
    assert messages[-1].status == MessageStatus.FAILED
    assert messages[-1].content == ""
    assert not any(event.event_type == "message.completed" for event in events)


def test_conversation_service_rejects_reused_client_id_with_different_content(tmp_path) -> None:
    store, service = make_service(tmp_path, FakeProvider(["첫 답변"]))
    conversation = store.create_conversation()

    list(service.stream_turn(conversation.id, content="첫 요청", client_message_id="same"))

    with pytest.raises(ValueError, match="different message content"):
        service.prepare_turn(
            conversation.id,
            content="다른 요청",
            client_message_id="same",
        )


def test_conversation_service_replays_non_local_idempotent_turns(tmp_path) -> None:
    store, service = make_service(tmp_path, FakeProvider(["답변"]))
    conversation = store.create_conversation(user_id="user-a")

    first, created = service.prepare_turn(
        conversation.id,
        content="사용자 A 요청",
        client_message_id="user-a-client",
        user_id="user-a",
    )
    second, replayed = service.prepare_turn(
        conversation.id,
        content="사용자 A 요청",
        client_message_id="user-a-client",
        user_id="user-a",
    )

    assert created is True
    assert replayed is False
    assert second.id == first.id


def test_conversation_service_retries_non_local_request_with_owner_scope(tmp_path) -> None:
    store, service = make_service(tmp_path, FakeProvider(["답변"]))
    conversation = store.create_conversation(user_id="user-a")
    original, _created = service.prepare_turn(
        conversation.id,
        content="재시도할 요청",
        client_message_id="retry-client",
        user_id="user-a",
    )
    store.transition_request(original.id, RequestState.FAILED, error_code="provider_failed")

    retried = service.retry_request(original.id, user_id="user-a")

    assert retried.parent_request_id == original.id
    assert retried.conversation_id == conversation.id


def test_conversation_service_passes_owner_scope_to_user_aware_provider(tmp_path) -> None:
    provider = UserAwareProvider(["사용자별 답변"])
    store, service = make_service(tmp_path, provider)
    conversation = store.create_conversation(user_id="user-a")
    request, _created = service.prepare_turn(
        conversation.id,
        content="사용자 A의 요청",
        client_message_id="user-a-provider",
        user_id="user-a",
    )

    list(service.run_request(request.id))

    assert provider.user_ids == ["user-a"]


def test_conversation_service_passes_request_and_conversation_scope(tmp_path) -> None:
    provider = RequestAwareProvider(["사용자별 답변"])
    store, service = make_service(tmp_path, provider)
    conversation = store.create_conversation(user_id="user-a")
    request, _created = service.prepare_turn(
        conversation.id,
        content="사용자 A의 요청",
        client_message_id="user-a-request-scope",
        user_id="user-a",
    )

    list(service.run_request(request.id))

    assert provider.scopes == [
        {
            "user_id": "user-a",
            "request_id": request.id,
            "conversation_id": conversation.id,
        }
    ]


def test_conversation_service_does_not_persist_a_late_cancelled_response(tmp_path) -> None:
    store, service = make_service(tmp_path, LateCancelProvider())
    conversation = store.create_conversation()
    request, _created = service.prepare_turn(
        conversation.id,
        content="취소된 요청",
        client_message_id="late-cancel",
    )

    events = list(service.run_request(request.id))

    persisted = store.get_messages(conversation.id)
    assert store.get_request(request.id).state == RequestState.CANCELLED
    assert [message.content for message in persisted] == ["취소된 요청", ""]
    assert persisted[-1].status == MessageStatus.CANCELLED
    assert not any(event.event_type == "message.completed" for event in events)
