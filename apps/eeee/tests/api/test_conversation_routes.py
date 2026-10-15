import json
import time

from fastapi.testclient import TestClient

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
