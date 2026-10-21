from pathlib import Path

import httpx

from app.agent.chatgpt_web_runtime import ChatGptWebRuntime
from app.agent.protocol import AgentRequest, AgentResult
from app.conversations.providers import ChatGptWebConversationProvider, ConversationProviderError


def _request() -> AgentRequest:
    return AgentRequest("사용자 요청", Path("."), [], "run-error-code")


def test_chatgpt_web_timeout_has_a_retryable_error_code(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent.chatgpt_web_runtime.httpx.post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("bridge timed out")),
    )

    result = ChatGptWebRuntime("http://127.0.0.1:47831").run(_request())

    assert result.status == "unavailable"
    assert result.error_code == "chatgpt_web_timeout"


def test_chatgpt_web_authentication_failure_has_a_specific_error_code(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "401 Unauthorized",
                request=httpx.Request("POST", "http://bridge/chat"),
                response=httpx.Response(401, json={"error": "login required"}),
            )

    monkeypatch.setattr("app.agent.chatgpt_web_runtime.httpx.post", lambda *_args, **_kwargs: FakeResponse())

    result = ChatGptWebRuntime("http://127.0.0.1:47831").run(_request())

    assert result.status == "unavailable"
    assert result.error_code == "chatgpt_web_auth_required"


def test_conversation_provider_preserves_runtime_error_code() -> None:
    class FakeRuntime:
        def run(self, _request):
            return AgentResult(
                status="unavailable",
                summary="",
                events=[],
                changed_files=[],
                test_commands=[],
                error="시간 초과",
                error_code="chatgpt_web_timeout",
            )

    provider = ChatGptWebConversationProvider(FakeRuntime())

    try:
        list(provider.stream([{"role": "user", "content": "안녕"}]))
    except ConversationProviderError as exc:
        assert exc.code == "chatgpt_web_timeout"
    else:  # pragma: no cover - the provider must reject unavailable results
        raise AssertionError("unavailable runtime result must raise ConversationProviderError")
