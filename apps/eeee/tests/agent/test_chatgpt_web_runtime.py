from pathlib import Path

import httpx

from app.agent.chatgpt_web_runtime import ChatGptWebRuntime
from app.agent.protocol import AgentRequest


def test_chatgpt_web_runtime_returns_bridge_response_and_keeps_conversation(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "completed", "message": "안녕! 오늘도 도와줄게.", "conversationRef": "conv-1"}

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return Response()

    monkeypatch.setattr(httpx, "post", post)
    runtime = ChatGptWebRuntime("http://127.0.0.1:47831")
    request = AgentRequest("사용자 요청: 안녕", Path("."), ["read"], "run-1")

    first = runtime.run(request)
    second = runtime.run(AgentRequest("사용자 요청: 뭐해?", Path("."), ["read"], "run-2"))

    assert first.status == "completed"
    assert first.summary == "안녕! 오늘도 도와줄게."
    assert second.status == "completed"
    assert calls[0][1]["conversationRef"] is None
    assert calls[1][1]["conversationRef"] == "conv-1"


def test_chatgpt_web_runtime_does_not_claim_success_when_bridge_is_down(monkeypatch):
    def post(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", post)
    result = ChatGptWebRuntime("http://127.0.0.1:47831").run(
        AgentRequest("사용자 요청: 안녕", Path("."), ["read"], "run-1")
    )

    assert result.status == "unavailable"
    assert result.error
