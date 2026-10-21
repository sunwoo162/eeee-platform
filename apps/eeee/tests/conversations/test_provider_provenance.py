from pathlib import Path

from app.conversations.service import ConversationService
from app.conversations.providers import build_conversation_provider
from app.conversations.providers import ConversationProviderError
from app.conversations.store import ConversationStore
from app.storage.sqlite import SQLiteStore


class IdentifiedProvider:
    provider_name = "chatgpt_web"
    model = "web-session"

    def stream(self, _messages, *, cancel_event=None):
        yield "실제 provider 답변"


class UnreadyWebRuntime:
    def status(self):
        return type("Status", (), {"status": "unavailable"})()


class BuiltinProvider:
    def stream(self, _messages, *, cancel_event=None):
        yield "기본 fallback 답변"


class FailingIdentifiedProvider(IdentifiedProvider):
    def stream(self, _messages, *, cancel_event=None):
        raise ConversationProviderError("timeout", code="chatgpt_web_timeout")
        yield "never"


def test_conversation_service_persists_provider_and_model_on_assistant_message(tmp_path: Path) -> None:
    durable = SQLiteStore(tmp_path / "state.sqlite3")
    durable.init()
    store = ConversationStore(durable)
    service = ConversationService(store, provider=IdentifiedProvider())
    conversation = store.create_conversation()

    list(
        service.stream_turn(
            conversation.id,
            content="어떤 AI가 답했는지 기록해줘",
            client_message_id="client-provenance",
        )
    )

    assistant = store.get_messages(conversation.id)[-1]
    assert assistant.provider == "chatgpt_web"
    assert assistant.model == "web-session"


def test_conversation_service_keeps_provider_provenance_on_failure(tmp_path: Path) -> None:
    durable = SQLiteStore(tmp_path / "state.sqlite3")
    durable.init()
    store = ConversationStore(durable)
    service = ConversationService(store, provider=FailingIdentifiedProvider())
    conversation = store.create_conversation()

    list(
        service.stream_turn(
            conversation.id,
            content="오류 원인도 기록해줘",
            client_message_id="client-provenance-failure",
        )
    )

    assistant = store.get_messages(conversation.id)[-1]
    assert assistant.provider == "chatgpt_web"
    assert assistant.model == "web-session"
    assert assistant.error_code == "chatgpt_web_timeout"


def test_web_fallback_exposes_the_provider_that_actually_answered() -> None:
    selection = build_conversation_provider(
        "chatgpt_web",
        ollama=None,
        web=UnreadyWebRuntime(),
        builtin=BuiltinProvider(),
    )

    assert list(selection.provider.stream([{"role": "user", "content": "안녕"}])) == [
        "기본 fallback 답변"
    ]
    assert selection.provider.active_provider_name == "builtin"
