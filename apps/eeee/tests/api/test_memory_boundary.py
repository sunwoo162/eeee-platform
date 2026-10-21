from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_explicit_memory_api_is_separate_from_conversation_search(tmp_path):
    client = TestClient(
        create_app(Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces"))
    )

    created = client.post(
        "/api/memory",
        json={
            "content": "항상 한국어로 답해",
            "sourceMessageId": "message-1",
            "actor": "user",
        },
    )
    assert created.status_code == 201
    memory = created.json()
    assert memory["source_type"] == "conversation"
    assert memory["source_message_id"] == "message-1"

    edited = client.patch(
        f"/api/memory/{memory['id']}",
        json={"content": "항상 짧은 한국어로 답해", "actor": "user"},
    )
    assert edited.status_code == 200
    assert edited.json()["content"] == "항상 짧은 한국어로 답해"

    revoked = client.post(
        f"/api/memory/{memory['id']}/revoke",
        json={"reason": "더 이상 필요 없음"},
    )
    assert revoked.status_code == 200
    assert client.get("/api/memory", params={"query": "짧은"}).json() == []


def test_chat_history_api_lists_opens_searches_and_sends_in_the_same_conversation(tmp_path):
    client = TestClient(
        create_app(Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces"))
    )

    first = client.post(
        "/api/assistant/route",
        json={"conversationId": "desktop-default", "text": "첫 명령"},
    )
    assert first.status_code == 200

    listed = client.get("/api/assistant/conversations")
    assert listed.status_code == 200
    assert listed.json()[0]["conversationId"] == "desktop-default"
    assert listed.json()[0]["messageCount"] == 2

    canonical = client.get("/v1/conversations")
    assert canonical.status_code == 200
    assert canonical.json()["items"][0]["id"] == "desktop-default"
    assert canonical.json()["items"][0]["messageCount"] == 2

    canonical_messages = client.get("/v1/conversations/desktop-default/messages")
    assert canonical_messages.status_code == 200
    assert [item["role"] for item in canonical_messages.json()["items"]] == [
        "user", "assistant"
    ]

    opened = client.get("/api/assistant/conversations/desktop-default", params={"limit": 10})
    assert opened.status_code == 200
    assert [item["role"] for item in opened.json()["turns"]] == ["user", "assistant"]

    searched = client.get("/api/assistant/conversations", params={"query": "첫 명령"})
    assert searched.status_code == 200
    assert [item["conversationId"] for item in searched.json()] == ["desktop-default"]

    second = client.post(
        "/api/assistant/route",
        json={"conversationId": "desktop-default", "text": "두 번째 명령"},
    )
    assert second.status_code == 200
    opened_again = client.get("/api/assistant/conversations/desktop-default")
    assert opened_again.json()["turns"][-2]["content"] == "두 번째 명령"
