from pathlib import Path
import json
from threading import Lock, Thread
import time

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


def test_chatgpt_web_runtime_serializes_shared_conversation_turns(monkeypatch):
    active = 0
    maximum = 0
    state_lock = Lock()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "completed", "message": "ok", "conversationRef": "conv-1"}

    def post(*_args, **_kwargs):
        nonlocal active, maximum
        with state_lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.05)
        with state_lock:
            active -= 1
        return Response()

    monkeypatch.setattr(httpx, "post", post)
    runtime = ChatGptWebRuntime("http://127.0.0.1:47831")
    threads = [
        Thread(target=runtime.run, args=(AgentRequest("work", Path("."), [], f"run-{index}"),))
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert maximum == 1


def test_chatgpt_web_runtime_does_not_claim_success_when_bridge_is_down(monkeypatch):
    def post(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", post)
    result = ChatGptWebRuntime("http://127.0.0.1:47831").run(
        AgentRequest("사용자 요청: 안녕", Path("."), ["read"], "run-1")
    )

    assert result.status == "unavailable"


def test_chatgpt_web_runtime_preserves_bridge_error_body(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "503 Service Unavailable",
                request=httpx.Request("POST", "http://bridge/chat"),
                response=httpx.Response(
                    503,
                    json={"status": "blocked", "error": "structured parser rejected response"},
                ),
            )

        def json(self):
            return {"status": "blocked", "error": "structured parser rejected response"}

    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: FakeResponse())
    result = ChatGptWebRuntime("http://127.0.0.1:47831").run(
        AgentRequest("work", Path("."), [], "run-error-body")
    )

    assert result.status == "unavailable"
    assert "structured parser rejected response" in (result.error or "")


def test_chatgpt_web_runtime_retries_one_transient_bridge_failure(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self.payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"{self.status_code} Service Unavailable",
                    request=httpx.Request("POST", "http://bridge/chat"),
                    response=httpx.Response(self.status_code, json=self.payload),
                )

        def json(self):
            return self.payload

    def fake_post(*_args, **_kwargs):
        calls.append(True)
        return (
            FakeResponse(503, {"status": "blocked", "error": "temporary bridge outage"})
            if len(calls) == 1
            else FakeResponse(200, {"status": "completed", "message": "다시 연결됐어.", "conversationRef": "conv-retry"})
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    result = ChatGptWebRuntime("http://127.0.0.1:47831").run(
        AgentRequest("안녕", Path("."), [], "run-retry")
    )

    assert result.status == "completed"
    assert result.summary == "다시 연결됐어."
    assert len(calls) == 2


def test_chatgpt_web_runtime_localizes_authentication_required(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "401 Unauthorized",
                request=httpx.Request("POST", "http://bridge/chat"),
                response=httpx.Response(
                    401,
                    json={"status": "blocked", "error": "Authenticated ChatGPT composer is missing or ambiguous: locator-missing"},
                ),
            )

    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: FakeResponse())
    result = ChatGptWebRuntime("http://127.0.0.1:47831").run(
        AgentRequest("안녕", Path("."), [], "run-auth")
    )

    assert result.status == "unavailable"
    assert "ChatGPT 로그인이 필요해" in (result.error or "")
    assert "locator-missing" not in (result.error or "")


def test_chatgpt_web_runtime_can_request_an_isolated_conversation(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"])
        return FakeResponse({"status": "completed", "message": "ok", "conversationRef": "conv-isolated"})

    monkeypatch.setattr("app.agent.chatgpt_web_runtime.httpx.post", fake_post)
    runtime = ChatGptWebRuntime("http://127.0.0.1:47831", fresh_conversation=True)
    result = runtime.run(AgentRequest("work", Path("."), [], "run-isolated"))

    assert result.status == "completed"
    assert calls[0]["newConversation"] is True
    assert result.summary == "ok"


def test_chatgpt_web_runtime_can_request_specialist_agent_contract(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "completed", "message": '{"summary":"ok","actions":[],"done":true}'}

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"])
        return FakeResponse()

    monkeypatch.setattr("app.agent.chatgpt_web_runtime.httpx.post", fake_post)
    runtime = ChatGptWebRuntime(
        "http://127.0.0.1:47831",
        fresh_conversation=True,
        mode="agent",
    )
    result = runtime.run(AgentRequest("work", Path("."), [], "run-agent"))

    assert result.status == "completed"
    assert calls[0]["mode"] == "agent"


def test_fresh_conversation_is_only_used_for_first_specialist_turn(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "completed", "message": "ok", "conversationRef": "conv-continued"}

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"])
        return FakeResponse()

    monkeypatch.setattr("app.agent.chatgpt_web_runtime.httpx.post", fake_post)
    runtime = ChatGptWebRuntime("http://127.0.0.1:47831", fresh_conversation=True, mode="agent")

    runtime.run(AgentRequest("first", Path("."), [], "run-first"))
    runtime.run(AgentRequest("second", Path("."), [], "run-second"))

    assert calls[0]["newConversation"] is True
    assert calls[1]["newConversation"] is False
    assert calls[1]["conversationRef"] == "conv-continued"


def test_chatgpt_web_runtime_sends_local_assistant_profile(monkeypatch, tmp_path):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "completed", "message": "반가워!", "conversationRef": "profile-conv"}

    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        '{"name":"모모","avatar":"🦊","personality":"차분한 코치","tone":"짧고 다정하게","role":"생활 비서"}',
        encoding="utf-8",
    )

    def fake_post(_url, **kwargs):
        calls.append(kwargs["json"])
        return FakeResponse()

    monkeypatch.setattr("app.agent.chatgpt_web_runtime.httpx.post", fake_post)
    runtime = ChatGptWebRuntime("http://127.0.0.1:47831", profile_path=profile_path)
    result = runtime.run(AgentRequest("안녕", Path("."), [], "run-profile"))

    assert result.status == "completed"
    assert calls[0]["profile"] == {
        "name": "모모",
        "avatar": "🦊",
        "personality": "차분한 코치",
        "tone": "짧고 다정하게",
        "role": "생활 비서",
    }


def test_chatgpt_web_runtime_restores_conversation_ref_from_local_state(monkeypatch, tmp_path):
    calls = []
    state_path = tmp_path / "chatgpt-assistant-conversation.json"
    state_path.write_text(json.dumps({"conversationRef": "persisted-conv"}), encoding="utf-8")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "completed", "message": "이어갈게!", "conversationRef": "persisted-conv"}

    def fake_post(_url, **kwargs):
        calls.append(kwargs["json"])
        return FakeResponse()

    monkeypatch.setattr("app.agent.chatgpt_web_runtime.httpx.post", fake_post)
    runtime = ChatGptWebRuntime(
        "http://127.0.0.1:47831",
        conversation_state_path=state_path,
    )

    result = runtime.run(AgentRequest("전에 하던 이야기 이어서", Path("."), [], "run-restore"))

    assert result.status == "completed"
    assert calls[0]["conversationRef"] == "persisted-conv"


def test_chatgpt_web_runtime_persists_only_conversation_ref_after_success(monkeypatch, tmp_path):
    state_path = tmp_path / "nested" / "conversation.json"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "completed", "message": "저장했어.", "conversationRef": "conv-saved"}

    monkeypatch.setattr("app.agent.chatgpt_web_runtime.httpx.post", lambda *_args, **_kwargs: FakeResponse())
    runtime = ChatGptWebRuntime(
        "http://127.0.0.1:47831",
        conversation_state_path=state_path,
    )

    result = runtime.run(AgentRequest("기억 이어가기", Path("."), [], "run-save"))

    assert result.status == "completed"
    assert json.loads(state_path.read_text(encoding="utf-8")) == {"conversationRef": "conv-saved"}


def test_chatgpt_web_runtime_clears_persisted_ref_on_auth_failure(monkeypatch, tmp_path):
    state_path = tmp_path / "conversation.json"
    state_path.write_text(json.dumps({"conversationRef": "stale-conv"}), encoding="utf-8")

    class FakeResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "401 Unauthorized",
                request=httpx.Request("POST", "http://bridge/chat"),
                response=httpx.Response(401, json={"error": "login required"}),
            )

    monkeypatch.setattr("app.agent.chatgpt_web_runtime.httpx.post", lambda *_args, **_kwargs: FakeResponse())
    runtime = ChatGptWebRuntime(
        "http://127.0.0.1:47831",
        conversation_state_path=state_path,
    )

    result = runtime.run(AgentRequest("안녕", Path("."), [], "run-auth-clear"))

    assert result.status == "unavailable"
    assert not state_path.exists()
