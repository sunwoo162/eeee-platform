"""Project memories have owner-scoped, append-only revisions and traceable origins."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _setup(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "work"))
    client = TestClient(app)
    wid = client.post("/v1/workspaces", json={"name":"Private"}).json()["id"]
    pid = client.post(f"/v1/workspaces/{wid}/projects", json={"name":"App"}).json()["id"]
    chat = client.post(f"/v1/projects/{pid}/conversations", json={"title":"New"}).json()["id"]
    return app, client, pid, chat


def test_memory_history_edit_revoke_and_context(tmp_path):
    app, client, pid, chat = _setup(tmp_path)
    created = client.post(f"/v1/projects/{pid}/memories", json={"content":"Use FastAPI"})
    assert created.status_code == 201, created.text
    mid = created.json()["id"]
    history_url = f"/v1/projects/{pid}/memories/{mid}/history"
    first = client.get(history_url)
    assert first.status_code == 200, first.text
    assert first.json()["revisions"][0]["action"] == "created"
    assert first.json()["revisions"][0]["version"] == 1

    wrong_user = {"X-EEEE-User-Id":"not-owner"}
    assert client.get(history_url, headers=wrong_user).status_code == 404
    assert client.put(f"/v1/projects/{pid}/memories/{mid}", json={
        "content":"Use Django", "expectedVersion":1,
    },headers=wrong_user).status_code == 404

    changed = client.put(f"/v1/projects/{pid}/memories/{mid}", json={
        "content":"Use Flask", "expectedVersion":1,
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2
    assert "Use Flask" in str(app.state.workspace_store.context_items(chat,user_id="local-user"))
    assert "Use FastAPI" not in str(app.state.workspace_store.context_items(chat,user_id="local-user"))

    stale = client.put(f"/v1/projects/{pid}/memories/{mid}", json={
        "content":"Use Starlette", "expectedVersion":1,
    })
    assert stale.status_code == 400
    assert "Use Flask" in client.get(history_url).json()["memory"]["content"]
    assert client.put(f"/v1/projects/{pid}/memories/{mid}", json={
        "content":"Use Flask", "expectedVersion":2,
    }).json()["version"] == 2
    assert client.delete(f"/v1/projects/{pid}/memories/{mid}").status_code == 200
    final = client.get(history_url).json()
    assert final["memory"]["status"] == "revoked"
    assert [r["action"] for r in final["revisions"]] == ["revoked","updated","created"]
    assert [r["version"] for r in final["revisions"]] == [3,2,1]
    assert final["revisions"][1]["old_content"] == "Use FastAPI"
    assert final["revisions"][1]["new_content"] == "Use Flask"
    assert not app.state.workspace_store.context_items(chat,user_id="local-user")
    assert client.put(f"/v1/projects/{pid}/memories/{mid}", json={
        "content":"Use FastAPI", "expectedVersion":3,
    }).status_code == 404


def test_origin_for_approved_import_memory(tmp_path):
    _, client, pid, _ = _setup(tmp_path)
    record = [{
        "id":"chatgpt-origin-123","title":"Original discussion",
        "current_node":"u",
        "mapping":{"u":{"parent":None,"message":{
            "author":{"role":"user"},
            "content":{"content_type":"text","parts":["프로젝트는 FastAPI를 사용한다"]},
        }}},
    }]
    saved = client.post("/v1/imports/commit",json={
        "provider":"chatgpt","content":json.dumps(record,ensure_ascii=False),
        "selectedIndexes":[0],"projectId":pid,
    })
    assert saved.status_code == 200, saved.text
    cid = saved.json()["imported"][0]["conversationId"]
    message = client.get(f"/v1/conversations/{cid}/messages").json()["items"][0]
    url=f"/v1/imports/projects/{pid}/memory-candidates/{message['id']}/review"
    approved=client.post(url,json={
        "decision":"approve","content":"프로젝트는 FastAPI를 사용한다",
    })
    assert approved.status_code == 200, approved.text
    mid=approved.json()["memoryId"]
    history=client.get(f"/v1/projects/{pid}/memories/{mid}/history").json()
    assert history["memory"]["source_message_id"] == message["id"]
    assert history["memory"]["source_content"] == "프로젝트는 FastAPI를 사용한다"
    assert history["memory"]["source_title"] == "Original discussion"
    assert history["memory"]["import_provider"] == "chatgpt"
    assert history["memory"]["import_source_id"] == "chatgpt-origin-123"
    assert history["revisions"][0]["source_message_id"] == message["id"]


def test_memory_analysis_invalidated_by_update(tmp_path):
    app, client, pid, _ = _setup(tmp_path)
    from app.conversation_imports.candidates import memory_set_digest
    initial=client.post(f"/v1/projects/{pid}/memories",json={"content":"Use FastAPI"})
    mid=initial.json()["id"]
    before=memory_set_digest(app.state.workspace_store.list_memories(pid,user_id="local-user"))
    client.put(f"/v1/projects/{pid}/memories/{mid}",json={
        "content":"Use Flask","expectedVersion":1,
    })
    after=memory_set_digest(app.state.workspace_store.list_memories(pid,user_id="local-user"))
    assert before!=after


def test_schema_migration_backfills_snapshot_without_fabricated_history(tmp_path):
    app, client, pid, _ = _setup(tmp_path)
    mid=client.post(f"/v1/projects/{pid}/memories",json={"content":"Keep provenance"}).json()["id"]
    with app.state.workspace_store.db._connect() as conn:
        conn.execute("DELETE FROM chat_memory_revisions WHERE memory_id=?",(mid,))
        conn.execute("DELETE FROM schema_migrations WHERE version=13")
    from app.storage.migrations import apply_migrations
    with app.state.workspace_store.db._connect() as conn:
        apply_migrations(conn)
    history=client.get(f"/v1/projects/{pid}/memories/{mid}/history").json()
    assert len(history["revisions"])==1
    assert history["revisions"][0]["action"]=="legacy_snapshot"


def test_shared_team_note_does_not_reveal_another_users_raw_source(tmp_path):
    app = create_app(Settings(data_dir=tmp_path/"data", workspace_root=tmp_path/"work"))
    client=TestClient(app)
    h={"X-EEEE-User-Id":"alice"}
    wid=client.post("/v1/workspaces",json={"name":"Team","kind":"team"},headers=h).json()["id"]
    pid=client.post(f"/v1/workspaces/{wid}/projects",json={"name":"Shared"},headers=h).json()["id"]
    cid=client.post(f"/v1/projects/{pid}/conversations",json={"title":"private notes"},headers=h).json()["id"]
    from app.conversations.models import MessageRole, MessageStatus
    msg=app.state.conversation_store.add_message(
        cid,role=MessageRole.USER,content="Private quote, not for members",
        status=MessageStatus.COMPLETED,
    )
    mid=client.post(f"/v1/projects/{pid}/memories",json={
        "content":"Approved project decision","source_message_id":msg.id,
    },headers=h).json()["id"]
    with app.state.workspace_store.db._connect() as conn:
        conn.execute(
            "INSERT INTO chat_workspace_members(workspace_id,user_id,role) VALUES (?,?,'viewer')",
            (wid,"bob"),
        )
    data=client.get(f"/v1/projects/{pid}/memories/{mid}/history",headers={
        "X-EEEE-User-Id":"bob",
    })
    assert data.status_code==200,data.text
    detail=data.json()["memory"]
    assert detail["content"]=="Approved project decision"
    assert detail["source_content"] is None
    assert detail["source_title"] is None
    assert detail["import_source_id"] is None
    assert client.put(f"/v1/projects/{pid}/memories/{mid}",json={
        "content":"bad edit","expectedVersion":1,
    },headers={"X-EEEE-User-Id":"bob"}).status_code==403
