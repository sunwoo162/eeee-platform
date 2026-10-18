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
