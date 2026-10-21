import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent.ollama_runtime import OllamaRuntime
from app.config import Settings
from app.main import create_app


class FakeProvider:
    def __init__(self, chunks=None) -> None:
        self.chunks = list(chunks or ["로컬", " 답변"])

    def stream(self, messages, *, cancel_event=None):
        yield from self.chunks


def make_client(tmp_path, provider=None) -> TestClient:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspace")
    return TestClient(create_app(settings, conversation_provider=provider or FakeProvider()))


def test_v1_conversation_turn_persists_and_replays_events(tmp_path) -> None:
    client = make_client(tmp_path)

    created = client.post("/v1/conversations", json={"title": "테스트 대화"})
    assert created.status_code == 201
    conversation = created.json()

    submitted = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={"clientMessageId": "client-1", "content": "무엇을 할까요?"},
    )
    assert submitted.status_code == 202
    request_id = submitted.json()["requestId"]
    assert submitted.json()["state"] in {"persisted_user_message", "completed"}

    deadline = time.monotonic() + 2
    events = client.get(f"/v1/requests/{request_id}/events")
    while time.monotonic() < deadline and "message.completed" not in events.text:
        time.sleep(0.01)
        events = client.get(f"/v1/requests/{request_id}/events")
    assert events.status_code == 200
    event_lines = [
        json.loads(line.removeprefix("data: "))
        for line in events.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [item["eventType"] for item in event_lines] == [
        "request.accepted",
        "request.classified",
        "message.started",
        "message.delta",
        "message.delta",
        "message.completed",
    ]

    messages = client.get(f"/v1/conversations/{conversation['id']}/messages")
    assert messages.status_code == 200
    assert [item["content"] for item in messages.json()["items"]] == [
        "무엇을 할까요?",
        "로컬 답변",
    ]


def test_v1_turn_submission_is_idempotent_for_client_message_id(tmp_path) -> None:
    client = make_client(tmp_path)
    conversation = client.post("/v1/conversations", json={}).json()
    path = f"/v1/conversations/{conversation['id']}/turns"

    first = client.post(path, json={"clientMessageId": "same", "content": "한 번만"})
    second = client.post(path, json={"clientMessageId": "same", "content": "한 번만"})

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["requestId"] == first.json()["requestId"]
    client.get(f"/v1/requests/{first.json()['requestId']}/events")
    assert len(client.get(f"/v1/conversations/{conversation['id']}/messages").json()["items"]) == 2


def test_v1_default_turn_uses_builtin_fallback_and_persists_messages(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspace",
        chatgpt_web_enabled=True,
        chatgpt_web_bridge_url="http://127.0.0.1:1",
        ollama_model=None,
    )
    client = TestClient(create_app(settings))
    conversation = client.post("/v1/conversations", json={}).json()

    submitted = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={"clientMessageId": "builtin-1", "content": "안녕"},
    )
    assert submitted.status_code == 202

    request_id = submitted.json()["requestId"]
    deadline = time.monotonic() + 2
    events = client.get(f"/v1/requests/{request_id}/events")
    while time.monotonic() < deadline and "message.completed" not in events.text:
        time.sleep(0.01)
        events = client.get(f"/v1/requests/{request_id}/events")

    assert "message.completed" in events.text
    messages = client.get(f"/v1/conversations/{conversation['id']}/messages").json()["items"]
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[1]["status"] == "completed"
    assert "안녕" in messages[1]["content"]


def test_v1_complex_turn_stays_failed_without_provider(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspace",
        chatgpt_web_enabled=True,
        chatgpt_web_bridge_url="http://127.0.0.1:1",
        ollama_model=None,
    )
    client = TestClient(create_app(settings))
    conversation = client.post("/v1/conversations", json={}).json()

    submitted = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={"clientMessageId": "complex-1", "content": "코드 작성해줘"},
    )
    request_id = submitted.json()["requestId"]
    deadline = time.monotonic() + 2
    events = client.get(f"/v1/requests/{request_id}/events")
    while time.monotonic() < deadline and "request.failed" not in events.text:
        time.sleep(0.01)
        events = client.get(f"/v1/requests/{request_id}/events")

    assert "request.failed" in events.text
    messages = client.get(f"/v1/conversations/{conversation['id']}/messages").json()["items"]
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["status"] == "failed"
    assert messages[-1]["content"] == ""


def test_v1_conversation_list_includes_durable_message_count(tmp_path) -> None:
    client = make_client(tmp_path)
    conversation = client.post("/v1/conversations", json={"title": "기록"}).json()
    client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={"clientMessageId": "count-1", "content": "메시지 수를 세어줘"},
    )

    listed = client.get("/v1/conversations")

    assert listed.status_code == 200
    item = next(item for item in listed.json()["items"] if item["id"] == conversation["id"])
    assert item["messageCount"] == 1


def test_v1_runtime_reports_ollama_model_readiness_separately_from_core_health(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspace",
        ollama_model=None,
    )
    client = TestClient(create_app(settings, conversation_provider=FakeProvider()))

    health = client.get("/health")
    runtime = client.get("/v1/runtime")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert runtime.status_code == 200
    assert runtime.json()["core"]["status"] == "ready"
    assert runtime.json()["ollama"]["status"] == "model_missing"
    assert runtime.json()["conversationProvider"]["name"] == "injected"


def test_v1_runtime_labels_active_builtin_fallback_and_keeps_ollama_unavailable(
    tmp_path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspace",
        conversation_provider="ollama",
        ollama_base_url="http://127.0.0.1:1",
        ollama_model="qwen3:4b",
        ollama_connect_timeout_seconds=0.1,
        ollama_generation_timeout_seconds=0.1,
    )
    client = TestClient(create_app(settings))

    runtime = client.get("/v1/runtime")

    assert runtime.status_code == 200
    payload = runtime.json()
    assert payload["ollama"]["status"] == "unavailable"
    assert payload["providers"]["ollama"]["status"] == "unavailable"
    assert payload["conversationProvider"]["name"] == "ollama"
    assert payload["conversationProvider"]["status"] == "unavailable"
    assert payload["conversationProvider"]["reason"] == (
        "explicit_local_provider_unavailable_builtin_fallback"
    )
    assert payload["conversationProvider"]["fallback"] == {
        "name": "builtin",
        "scope": "basic_only",
        "active": True,
    }


def test_v1_runtime_refreshes_web_status_after_login(tmp_path) -> None:
    class FakeWebRuntime:
        def __init__(self) -> None:
            self.ready = False

        def status(self):
            return SimpleNamespace(status="ready" if self.ready else "auth-required")

    web = FakeWebRuntime()
    from app.api.conversation_routes import build_conversation_router
    from app.conversations.providers import build_conversation_provider
    from app.conversations.service import ConversationService
    from app.conversations.store import ConversationStore
    from app.storage.sqlite import SQLiteStore
    from fastapi import FastAPI
    from app.agent.ollama_runtime import OllamaRuntime

    store = SQLiteStore(tmp_path / "runtime.sqlite3")
    store.init()
    service = ConversationService(ConversationStore(store), provider=FakeProvider())
    selection = build_conversation_provider("chatgpt_web", ollama=None, web=web)
    application = FastAPI()
    application.include_router(
        build_conversation_router(
            service,
            ollama=OllamaRuntime(base_url="http://127.0.0.1:11434", model=None),
            provider_selection=selection,
            web_configured=True,
            web_status="auth-required",
            web_status_provider=web.status,
        )
    )
    client = TestClient(application)

    assert client.get("/v1/runtime").json()["providers"]["chatgpt_web"]["status"] == "auth-required"
    web.ready = True
    runtime = client.get("/v1/runtime").json()
    assert runtime["providers"]["chatgpt_web"]["status"] == "ready"
    assert runtime["conversationProvider"]["status"] == "configured"


@pytest.mark.parametrize("mode", ["chatgpt_web", "auto"])
def test_v1_runtime_reports_builtin_fallback_metadata_for_wrapped_web_selection(
    mode, tmp_path
) -> None:
    class FakeWebRuntime:
        def __init__(self) -> None:
            self.ready = False

        def status(self):
            return SimpleNamespace(status="ready" if self.ready else "auth-required")

    from app.api.conversation_routes import build_conversation_router
    from app.conversations.providers import BuiltinConversationProvider, build_conversation_provider
    from app.conversations.service import ConversationService
    from app.conversations.store import ConversationStore
    from app.storage.sqlite import SQLiteStore
    from fastapi import FastAPI

    web = FakeWebRuntime()
    store = SQLiteStore(tmp_path / f"{mode}.sqlite3")
    store.init()
    service = ConversationService(ConversationStore(store), provider=FakeProvider())
    selection = build_conversation_provider(
        mode,
        ollama=None,
        web=web,
        builtin=BuiltinConversationProvider(),
    )
    application = FastAPI()
    application.include_router(
        build_conversation_router(
            service,
            ollama=OllamaRuntime(base_url="http://127.0.0.1:11434", model=None),
            provider_selection=selection,
            web_configured=True,
            web_status_provider=web.status,
        )
    )
    client = TestClient(application)

    unavailable = client.get("/v1/runtime").json()["conversationProvider"]
    assert unavailable["fallback"] == {
        "name": "builtin",
        "scope": "basic_only",
        "active": True,
    }

    web.ready = True
    configured = client.get("/v1/runtime").json()["conversationProvider"]
    assert configured["fallback"] == {
        "name": "builtin",
        "scope": "basic_only",
        "active": False,
    }
