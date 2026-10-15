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
