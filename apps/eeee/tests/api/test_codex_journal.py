"""Codex agent state and approvals remain auditable across server restarts."""

import pytest
from fastapi.testclient import TestClient

from app.codex_integration.journal import CodexJournal
from app.config import Settings
from app.main import create_app
from app.storage.sqlite import SQLiteStore


def test_codex_journal_restores_completed_task_and_approval_audit(tmp_path, monkeypatch):
    db = SQLiteStore(tmp_path / "state.sqlite3")
    db.init()
    # journal FK demands an owned conversation/project; create through the normal app.
    app = create_app(Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "work"))
    client = TestClient(app)
    root = tmp_path / "work"
    (root / "existing").mkdir(parents=True)
    wid = client.post("/v1/workspaces", json={"name":"P","kind":"personal"}).json()["id"]
    pid = client.post(f"/v1/workspaces/{wid}/projects", json={"name":"Gleave"}).json()["id"]
    cid = client.post(f"/v1/projects/{pid}/conversations", json={}).json()["id"]
    client.put(f"/v1/projects/{pid}/codex/directory", json={"relativePath":"existing"})
    manager = app.state.codex_manager
    manager.executable = "fake"
    def simulate(task, command):
        task.status = "running"
        task.publish("started", "sandbox read only")
        task.answer = "ok"
        task.status = "completed"
        task.publish("completed", "completed")
        manager.journal.save(task)
        manager.on_finished(task)
    monkeypatch.setattr(manager, "_execute", simulate)
    res = client.post(f"/v1/projects/{pid}/codex/tasks", json={
        "conversationId":cid,"prompt":"Assess the project",
    })
    assert res.status_code == 202, res.text
    task_id = res.json()["id"]
    import time
    for _ in range(80):
        result = client.get(f"/v1/codex/tasks/{task_id}").json()
        if result["status"] == "completed":
            break
        time.sleep(0.01)
    assert result["status"] == "completed"
    audit = client.get(f"/v1/codex/tasks/{task_id}/audit").json()["items"]
    assert any(row["kind"] == "started" for row in audit)
    assert client.get(f"/v1/codex/tasks/{task_id}", headers={"X-EEEE-User-Id":"intruder"}).status_code == 404

    # Create a new process/store instance; running manager's tasks are not reused.
    second = create_app(Settings(data_dir=tmp_path / "data", workspace_root=root))
    second_client = TestClient(second)
    record = second_client.get(f"/v1/codex/tasks/{task_id}")
    assert record.status_code == 200
    assert record.json()["status"] == "completed"
    assert second_client.get(f"/v1/conversations/{cid}/codex/tasks").json()["items"][0]["id"] == task_id
    assert second_client.get(f"/v1/codex/tasks/{task_id}/audit").json()["items"]


def test_restart_invalidates_pending_approval_without_implicit_acceptance(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "work"))
    client = TestClient(app)
    wid = client.post("/v1/workspaces", json={"name":"P"}).json()["id"]
    pid = client.post(f"/v1/workspaces/{wid}/projects", json={"name":"Gleave"}).json()["id"]
    cid = client.post(f"/v1/projects/{pid}/conversations", json={}).json()["id"]
    journal = app.state.codex_manager.journal
    from app.codex_integration.runtime import CodexTask
    task = CodexTask(
        id="codex-task-stale", user_id="local-user", project_id=pid, conversation_id=cid,
        directory=str(tmp_path), prompt="x", display_prompt="x", mode="workspaceWrite",
        status="approvalRequired", pending_approval={"id":"stale","method":"item/fileChange/requestApproval"},
    )
    journal.save(task)
    journal.append_audit(task,kind="approvalRequested", details={"id":"stale"})
    another = CodexJournal(app.state.workspace_store.db)
    recovered = another.snapshot(task.id, user_id="local-user")
    assert recovered["status"] == "interrupted"
    assert recovered["pendingApproval"] is None
    assert any(event["kind"] == "interrupted" for event in another.audit(task.id,user_id="local-user"))
    assert client.post(f"/v1/codex/tasks/{task.id}/approval",json={"approvalId":"stale","decision":"accept"}).status_code == 404
    with pytest.raises(KeyError):
        another.snapshot(task.id,user_id="other")
