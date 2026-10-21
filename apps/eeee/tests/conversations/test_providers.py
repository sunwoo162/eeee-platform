from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from app.agent.ollama_runtime import OllamaRuntime
from app.agent.protocol import AgentRequest, AgentResult
from app.conversations.providers import (
    ConversationProviderError,
    build_conversation_provider,
)


class FakeWebRuntime:
    def __init__(self, result: AgentResult | None = None) -> None:
        self.result = result or AgentResult(
            status="completed",
            summary="Web GPT 답변",
            events=[],
            changed_files=[],
            test_commands=[],
            error=None,
        )
        self.requests: list[AgentRequest] = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        return self.result


class UnreadyWebRuntime(FakeWebRuntime):
    def status(self):
        return SimpleNamespace(status="unavailable", model=None, message="bridge down")


class FakeOllama:
    model = "qwen3:4b"

    def stream(self, _messages, *, cancel_event=None):
        if cancel_event is not None and cancel_event.is_set():
            return
        yield "Ollama 답변"


class UnreadyOllama(FakeOllama):
    def status(self):
        return SimpleNamespace(
            status="unavailable", model=self.model, error_code="ollama_unavailable"
        )


class RecoveringOllama(FakeOllama):
    def __init__(self) -> None:
        self.ready = False
        self.status_calls = 0
        self.stream_calls = 0

    def status(self):
        self.status_calls += 1
        return SimpleNamespace(
            status="ready" if self.ready else "unavailable",
            model=self.model,
            error_code=None if self.ready else "ollama_unavailable",
        )

    def stream(self, messages, *, cancel_event=None):
        self.stream_calls += 1
        yield from super().stream(messages, cancel_event=cancel_event)


class EmptyOllama(FakeOllama):
    def stream(self, _messages, *, cancel_event=None):
        if cancel_event is not None and cancel_event.is_set():
            return
        yield from ()


class FakeBuiltin:
    def __init__(self) -> None:
        self.calls = 0

    def stream(self, _messages, *, cancel_event=None):
        self.calls += 1
        yield "builtin 답변"


def test_auto_selects_web_gpt_when_bridge_is_configured() -> None:
    web = FakeWebRuntime()

    selection = build_conversation_provider(
        "auto",
        ollama=FakeOllama(),
        web=web,
    )

    assert selection.provider_name == "chatgpt_web"
    assert selection.status == "configured"
    assert list(selection.provider.stream([
        {"role": "user", "content": "오늘 할 일을 정리해줘"},
    ])) == ["Web GPT 답변"]
    assert "오늘 할 일을 정리해줘" in web.requests[0].prompt


def test_explicit_web_gpt_does_not_fallback_to_ollama() -> None:
    selection = build_conversation_provider(
        "chatgpt_web",
        ollama=FakeOllama(),
        web=None,
    )

    assert selection.provider_name == "chatgpt_web"
    with pytest.raises(ConversationProviderError) as error:
        list(selection.provider.stream([], cancel_event=Event()))

    assert error.value.code == "chatgpt_web_unavailable"


def test_explicit_ollama_keeps_local_provider() -> None:
    selection = build_conversation_provider(
        "ollama",
        ollama=FakeOllama(),
        web=FakeWebRuntime(),
    )

    assert selection.provider_name == "ollama"
    assert list(selection.provider.stream([])) == ["Ollama 답변"]


def test_auto_reports_unavailable_when_no_provider_is_configured() -> None:
    selection = build_conversation_provider("auto", ollama=None, web=None)

    assert selection.status == "unavailable"
    with pytest.raises(ConversationProviderError) as error:
        list(selection.provider.stream([]))

    assert error.value.code == "chatgpt_web_unavailable"


def test_auto_does_not_fall_back_to_ollama_when_web_bridge_is_not_ready() -> None:
    selection = build_conversation_provider(
        "auto",
        ollama=FakeOllama(),
        web=UnreadyWebRuntime(),
    )

    assert selection.provider_name == "chatgpt_web"
    assert selection.status == "unavailable"
    assert selection.reason == "auto_selected_web_provider_but_not_ready"
    assert list(selection.provider.stream([])) == ["Web GPT 답변"]


def test_explicit_web_reports_unready_bridge_without_fallback() -> None:
    selection = build_conversation_provider(
        "chatgpt_web",
        ollama=FakeOllama(),
        web=UnreadyWebRuntime(),
    )

    assert selection.provider_name == "chatgpt_web"
    assert selection.status == "unavailable"
    assert list(selection.provider.stream([])) == ["Web GPT 답변"]


def test_unready_web_provider_can_retry_after_bridge_login() -> None:
    web = UnreadyWebRuntime()
    selection = build_conversation_provider(
        "chatgpt_web",
        ollama=FakeOllama(),
        web=web,
    )

    assert selection.status == "unavailable"
    assert list(selection.provider.stream([])) == ["Web GPT 답변"]


def test_web_prompt_respects_provider_context_budget() -> None:
    web = FakeWebRuntime()
    selection = build_conversation_provider(
        "chatgpt_web",
        ollama=FakeOllama(),
        web=web,
        context_tokens=32,
    )

    list(selection.provider.stream([
        {"role": "user", "content": "오래된 내용 " * 100},
        {"role": "user", "content": "마지막 요청"},
    ]))

    assert len(web.requests[0].prompt) <= 128


def test_unready_web_can_use_builtin_for_supported_basic_turns() -> None:
    from app.conversations.providers import BuiltinConversationProvider

    selection = build_conversation_provider(
        "chatgpt_web",
        ollama=None,
        web=UnreadyWebRuntime(),
        builtin=BuiltinConversationProvider(),
    )

    assert selection.provider_name == "chatgpt_web"
    assert selection.status == "unavailable"
    assert list(selection.provider.stream([{"role": "user", "content": "안녕"}]))[0].startswith("안녕!")


@pytest.mark.parametrize(
    "prompt",
    [
        "코드 작성해줘",
        "오늘 날씨 어때?",
        "대한민국의 수도는 어디야?",
        "오늘 기분이 어때? 날씨 알려줘",
    ],
)
def test_builtin_conversation_provider_rejects_unsupported_turns(prompt: str) -> None:
    from app.conversations.providers import BuiltinConversationProvider

    with pytest.raises(ConversationProviderError) as error:
        list(BuiltinConversationProvider().stream([{"role": "user", "content": prompt}]))

    assert error.value.code == "assistant_provider_unavailable"


def test_explicit_unready_ollama_uses_builtin_for_supported_basic_turns() -> None:
    from app.conversations.providers import BuiltinConversationProvider

    selection = build_conversation_provider(
        "ollama",
        ollama=UnreadyOllama(),
        web=None,
        builtin=BuiltinConversationProvider(),
    )

    assert selection.provider_name == "ollama"
    assert selection.status == "unavailable"
    assert selection.reason == "explicit_local_provider_unavailable_builtin_fallback"
    assert list(selection.provider.stream([{"role": "user", "content": "안녕"}]))[0].startswith("안녕!")


def test_explicit_ollama_rechecks_readiness_and_recovers_without_rebuilding_selection() -> None:
    from app.conversations.providers import BuiltinConversationProvider

    ollama = RecoveringOllama()
    selection = build_conversation_provider(
        "ollama",
        ollama=ollama,
        web=None,
        builtin=BuiltinConversationProvider(),
    )

    assert list(selection.provider.stream([{"role": "user", "content": "안녕"}]))[0].startswith("안녕!")
    ollama.ready = True

    assert list(selection.provider.stream([{"role": "user", "content": "안녕"}])) == [
        "Ollama 답변"
    ]
    assert ollama.status_calls >= 2
    assert ollama.stream_calls == 1


def test_explicit_unready_ollama_keeps_complex_turn_unavailable() -> None:
    from app.conversations.providers import BuiltinConversationProvider

    selection = build_conversation_provider(
        "ollama",
        ollama=UnreadyOllama(),
        web=None,
        builtin=BuiltinConversationProvider(),
    )

    with pytest.raises(ConversationProviderError) as error:
        list(selection.provider.stream([{"role": "user", "content": "코드 작성해줘"}]))

    assert error.value.code == "assistant_provider_unavailable"


def test_empty_ollama_stream_uses_builtin_for_explicitly_eligible_turn() -> None:
    builtin = FakeBuiltin()
    selection = build_conversation_provider(
        "ollama",
        ollama=EmptyOllama(),
        web=None,
        builtin=builtin,
    )

    assert list(selection.provider.stream([{"role": "user", "content": "안녕"}])) == [
        "builtin 답변"
    ]
    assert builtin.calls == 1


def test_empty_ollama_stream_rejects_turn_that_is_not_builtin_eligible() -> None:
    builtin = FakeBuiltin()
    selection = build_conversation_provider(
        "ollama",
        ollama=EmptyOllama(),
        web=None,
        builtin=builtin,
    )

    with pytest.raises(ConversationProviderError) as error:
        list(selection.provider.stream([{"role": "user", "content": "오늘 날씨 어때?"}]))

    assert error.value.code == "provider_empty_response"
    assert builtin.calls == 0
