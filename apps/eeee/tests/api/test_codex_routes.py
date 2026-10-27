"""Local Codex binding/API tests; no live Codex account or provider calls."""
import time

from fastapi.testclient import TestClient

from app.chat_scopes.store import WorkspaceStore
from app.config import Settings
from app.main import create_app


def _setup(tmp_path):
    data = tmp_path / "data"
    workspace_root = tmp_path / "work"
    folder = workspace_root / "repo1"
    folder.mkdir(parents=True)
    app = create_app(Settings(data_dir=data, workspace_root=workspace_root))
    client = TestClient(app)
    wid = client.post("/v1/workspaces", json={"kind": "personal", "name": "Mine"}).json()["id"]
    pid = client.post(f"/v1/workspaces/{wid}/projects", json={"name": "Gleave"}).json()["id"]
    chat = client.post(f"/v1/projects/{pid}/conversations", json={"title": "Dev"}).json()["id"]
    return app, client, pid, chat, folder


def test_directory_cannot_escape_bound_root_or_allow_team_viewer(tmp_path):
    app, client, pid, _, folder = _setup(tmp_path)
    invalid = ["../escape", "/tmp", "C:/Windows", "foo/../../escape", "..\\secrets", "."]
    for rel in invalid:
        r = client.put(f"/v1/projects/{pid}/codex/directory", json={"relativePath": rel})
        assert r.status_code == 409, (rel, r.text)
    not_found = client.put(f"/v1/projects/{pid}/codex/directory", json={"relativePath": "missing"})
    assert not_found.status_code == 409
    bound = client.put(f"/v1/projects/{pid}/codex/directory", json={"relativePath": "repo1"})
    assert bound.status_code == 200
    fetched = client.get(f"/v1/projects/{pid}/codex/directory")
    assert fetched.json()["directory"]["absolutePath"] == str(folder.resolve())
    other = client.get(f"/v1/projects/{pid}/codex/directory", headers={"X-EEEE-User-Id": "bob"})
    assert other.status_code == 404
    assert app.state.workspace_store.project_directory(
        pid, workspace_root=tmp_path / "work", user_id="local-user"
    ) is not None


def test_codex_task_requires_project_chat_and_write_confirmation(tmp_path, monkeypatch):
    app, client, pid, chat, _ = _setup(tmp_path)
    client.put(f"/v1/projects/{pid}/codex/directory", json={"relativePath": "repo1"})
    manager = app.state.codex_manager
    manager.executable = "fake-app-server"
    def fake_execute(task, command):
        task.status = "completed"
        task.answer = "Reviewed repository"
    monkeypatch.setattr(manager, "_execute", fake_execute)
    url = f"/v1/projects/{pid}/codex/tasks"
    missing_permission = client.post(url, json={
        "conversationId": chat, "prompt": "Refactor code", "mode": "workspaceWrite",
    })
    assert missing_permission.status_code == 403
    unrelated = client.post("/v1/conversations", json={}).json()["id"]
    assert client.post(url, json={"conversationId": unrelated, "prompt": "Hi"}).status_code == 409
    ok = client.post(url, json={"conversationId": chat, "prompt": "Explain this repo"})
    assert ok.status_code == 202
    task_id = ok.json()["id"]
    for _ in range(30):
        current = client.get(f"/v1/codex/tasks/{task_id}")
        if current.json()["status"] == "completed":
            break
        time.sleep(0.01)
    assert current.json()["answer"] == "Reviewed repository"
    assert client.get(
        f"/v1/codex/tasks/{task_id}", headers={"X-EEEE-User-Id": "other"}
    ).status_code == 404


def test_readonly_binding_rejects_symlink_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "shortcut"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        return  # Developer Mode/admin privileges may be needed on Windows.
    try:
        WorkspaceStore.validate_directory("shortcut", root)
    except ValueError:
        pass
    else:
        raise AssertionError("symlink escaped root")


def test_create_dedicated_project_directory_only_with_owner_access(tmp_path):
    _, client, pid, _, _ = _setup(tmp_path)
    created = client.post(f"/v1/projects/{pid}/codex/directory/create")
    assert created.status_code == 201, created.text
    name = created.json()["relativePath"]
    assert name == pid
    assert (tmp_path / "work" / name).is_dir()
    forged = client.post(
        f"/v1/projects/{pid}/codex/directory/create",
        headers={"X-EEEE-User-Id": "someone-else"},
    )
    assert forged.status_code == 404
