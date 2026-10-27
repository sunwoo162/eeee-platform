"""Project-folder API contract; no remote team invitations in local MVP."""
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class FakeProvider:
    def stream(self, messages, *, cancel_event=None):
        yield "ok"


def test_folder_chat_memory_api_and_project_reassignment(tmp_path):
    client = TestClient(create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "work"),
        conversation_provider=FakeProvider(),
    ))
    assert client.get("/v1/workspaces").json()["items"] == []
    owner = client.post("/v1/workspaces", json={"name": "Personal", "kind": "personal"})
    assert owner.status_code == 201
    wid = owner.json()["id"]
    first = client.post(f"/v1/workspaces/{wid}/projects", json={"name": "Gleave"})
    second = client.post(f"/v1/workspaces/{wid}/projects", json={"name": "RepoDock"})
    assert first.status_code == second.status_code == 201
    p1, p2 = first.json()["id"], second.json()["id"]

    chat = client.post(f"/v1/projects/{p1}/conversations", json={"title": "Design"})
    assert chat.status_code == 201
    cid = chat.json()["id"]
    assert client.get(f"/v1/conversations/{cid}/project").json()["project"]["id"] == p1
    assert client.get(f"/v1/projects/{p1}/conversations").json()["items"][0]["id"] == cid

    approved = client.post(f"/v1/projects/{p1}/memories", json={"content": "Use FastAPI"})
    assert approved.status_code == 201
    memory_id = approved.json()["id"]
    ctx = client.app.state.conversation_service.context_builder
    assert "Use FastAPI" in str(ctx.build(cid))
    assert client.delete(f"/v1/projects/{p1}/memories/{memory_id}").status_code == 200
    assert "Use FastAPI" not in str(ctx.build(cid))

    assert client.put(f"/v1/projects/{p2}/conversations/{cid}").status_code == 200
    assert client.get(f"/v1/projects/{p1}/conversations").json()["items"] == []
    assert client.get(f"/v1/conversations/{cid}/project").json()["project"]["id"] == p2


def test_folder_api_is_user_scoped(tmp_path):
    client = TestClient(create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "work"),
        conversation_provider=FakeProvider(),
    ))
    headers_a = {"X-EEEE-User-Id": "alice"}
    headers_b = {"X-EEEE-User-Id": "bob"}
    owner = client.post("/v1/workspaces", json={"name": "Private"}, headers=headers_a)
    assert owner.status_code == 201
    wid = owner.json()["id"]
    assert client.get("/v1/workspaces", headers=headers_b).json()["items"] == []
    assert client.get(f"/v1/workspaces/{wid}/projects", headers=headers_b).status_code == 404
    assert client.post(
        f"/v1/workspaces/{wid}/projects", json={"name": "Intruder"}, headers=headers_b
    ).status_code == 404
    assert client.post("/v1/workspaces", json={"name": "Team", "kind": "team"}, headers=headers_a).status_code == 201


def test_invalid_workspace_rejected(tmp_path):
    client = TestClient(create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "work"),
        conversation_provider=FakeProvider(),
    ))
    bad = client.post("/v1/workspaces", json={"name": "Bad", "kind": "unknown"})
    assert bad.status_code == 400
