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
