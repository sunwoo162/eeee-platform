"""Model choice is per turn, deterministic, persisted, and never silently rewritten."""
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.conversations.multimodel import (
    ClaudeMessagesProvider,
    OpenAIResponsesProvider,
    ProviderHub,
)
from app.conversations.providers import ConversationProviderError
from app.main import create_app


class FakeProvider:
    def __init__(self, text, name):
        self.text = text
        self.provider_name = name
        self.model = f"fake-{name}"

    def stream(self, messages, **kwargs):
        yield self.text


def sse(body):
    return "\n\n".join("data: " + json.dumps(part) for part in body) + "\n\n"


def test_gpt_stream_uses_responses_api_and_omits_secret_from_result():
    def callback(request):
        assert request.url.path == "/v1/responses"
        assert request.headers["authorization"] == "Bearer private-key"
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-6.1-sol"
        assert payload["stream"] is True
        return httpx.Response(200, text=sse([
            {"type": "response.output_text.delta", "delta": "안녕"},
            {"type": "response.output_text.delta", "delta": "하세요"},
            {"type": "response.completed"},
        ]))
    provider = OpenAIResponsesProvider(api_key="private-key", transport=httpx.MockTransport(callback))
    assert "".join(provider.stream([{"role": "user", "content": "Hi"}])) == "안녕하세요"


def test_claude_stream_extracts_text_and_system_context():
    def callback(request):
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "private-key"
        payload = json.loads(request.content)
        assert payload["system"] == "Approved project memory"
        assert payload["messages"] == [{"role": "user", "content": "질문"}]
        return httpx.Response(200, text=sse([
            {"type": "message_start"},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "답변"}},
            {"type": "message_stop"},
        ]))
    provider = ClaudeMessagesProvider(api_key="private-key", transport=httpx.MockTransport(callback))
    assert "".join(provider.stream([
        {"role": "system", "content": "Approved project memory"},
        {"role": "user", "content": "질문"},
    ])) == "답변"


def test_manual_unavailable_provider_is_not_silent_fallback():
    hub = ProviderHub(FakeProvider("old", "legacy"))
    with pytest.raises(ConversationProviderError) as exc:
        list(hub.select("gpt", [{"role": "user", "content": "hello"}]).stream([]))
    assert exc.value.code == "gpt_unavailable"
    assert hub.select("auto", [{"role": "user", "content": "hello"}]).provider_name == "legacy"
    with pytest.raises(ValueError):
        hub.select("evil", [])


def test_auto_uses_claude_for_code_or_gpt_for_general_request():
    hub = ProviderHub(FakeProvider("legacy", "legacy"), openai_key="fake", claude_key="fake")
    assert hub.select("auto", [{"role": "user", "content": "버그 고쳐줘"}]).provider_name == "claude"
    assert hub.select("auto", [{"role": "user", "content": "안녕"}]).provider_name == "gpt"
    assert hub.select("claude", [{"role": "user", "content": "안녕"}]).provider_name == "claude"


def test_selected_model_is_persisted_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "work"),
        conversation_provider=FakeProvider("AUTO", "legacy"),
    )
    hub = app.state.conversation_service.provider_hub
    hub.available["gpt"] = True
    hub.providers["gpt"] = FakeProvider("GPT_RESULT", "gpt")
    hub.gpt = hub.providers["gpt"]
    client = TestClient(app)
    models = client.get("/v1/providers")
    assert models.status_code == 200
    assert any(row["id"] == "gpt" for row in models.json()["items"])
    cid = client.post("/v1/conversations", json={"title": "Model switch"}).json()["id"]
    url = f"/v1/conversations/{cid}/turns"
    first = client.post(url, json={
        "clientMessageId": "manual-1", "content": "Test", "provider": "gpt",
    })
    assert first.status_code == 202
    request_id = first.json()["requestId"]
    assert app.state.conversation_store.get_request(request_id).selected_provider == "gpt"
    wrong = client.post(url, json={
        "clientMessageId": "manual-1", "content": "Test", "provider": "claude",
    })
    assert wrong.status_code == 409
    for _ in range(80):
        reply = client.get(f"/v1/conversations/{cid}/messages").json()["items"]
        if len(reply) == 2 and reply[-1]["status"] == "completed":
            break
        time.sleep(0.025)
    assert reply[-1]["content"] == "GPT_RESULT"
    assert reply[-1]["provider"] == "gpt"
    assert reply[-1]["model"] == "fake-gpt"

def test_unavailable_manual_choice_fails_instead_of_using_default(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "work"),
        conversation_provider=FakeProvider("MUST_NOT_APPEAR", "legacy"),
    )
    client = TestClient(app)
    cid = client.post("/v1/conversations", json={}).json()["id"]
    res = client.post(f"/v1/conversations/{cid}/turns", json={
        "clientMessageId": "manual-unavailable", "content": "Use Claude",
        "provider": "claude",
    })
    assert res.status_code == 202
    for _ in range(80):
        messages = client.get(f"/v1/conversations/{cid}/messages").json()["items"]
        if len(messages) == 2 and messages[-1]["status"] == "failed":
            break
        time.sleep(0.025)
    assert messages[-1]["status"] == "failed"
    assert messages[-1]["error_code"] == "claude_unavailable"
    assert "MUST_NOT_APPEAR" not in str(messages)
