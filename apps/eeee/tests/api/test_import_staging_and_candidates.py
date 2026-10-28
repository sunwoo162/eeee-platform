"""ZIP staging, archive safety, private ownership, and human memory review."""
from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _chat(number: int, text: str = "프로젝트는 FastAPI로 개발하기로 했어") -> dict:
    return {
        "id": f"original-{number}", "title": f"Conversation {number}",
        "current_node": "u", "mapping": {
            "u": {"parent": None, "message": {
                "author": {"role": "user"}, "content": {
                    "content_type": "text", "parts": [text],
                },
            }},
        },
    }


def _zip(lookup: dict[str, bytes]) -> bytes:
    file = io.BytesIO()
    with zipfile.ZipFile(file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in lookup.items():
            archive.writestr(path, content)
    return file.getvalue()


def _setup(tmp_path):
    app = create_app(Settings(
        data_dir=tmp_path / "data", workspace_root=tmp_path / "work",
    ))
    client = TestClient(app)
    space = client.post("/v1/workspaces", json={"name": "Private"}).json()["id"]
    project = client.post(f"/v1/workspaces/{space}/projects", json={"name": "Sample"}).json()["id"]
    sibling = client.post(
        f"/v1/projects/{project}/conversations", json={"title": "Existing"}
    ).json()["id"]
    return app, client, project, sibling


def test_large_zip_preview_is_paged_and_requires_explicit_commit(tmp_path):
    app, client, project, sibling = _setup(tmp_path)
    documents = [_chat(n) for n in range(130)]
    archive = _zip({
        "export/conversations.json": json.dumps(documents).encode(),
        "export/profile.json": b'{"sensitive": "ignored"}',
    })
    response = client.post(
        "/v1/imports/upload?provider=chatgpt&filename=export.zip",
        content=archive,
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 130 and len(page["items"]) == 40
    token = page["sessionId"]
    assert len(client.get(f"/v1/projects/{project}/conversations").json()["items"]) == 1
    final_page = client.get(f"/v1/imports/sessions/{token}?offset=120&limit=40")
    assert final_page.status_code == 200
    assert [row["index"] for row in final_page.json()["items"]] == list(range(120,130))
    assert client.get(
        f"/v1/imports/sessions/{token}",
        headers={"X-EEEE-User-Id": "unauthorized"},
    ).status_code == 404
    commit = client.post(f"/v1/imports/sessions/{token}/commit", json={
        "selectedIndexes": [0, 129], "projectId": project,
    })
    assert commit.status_code == 200, commit.text
    assert len(commit.json()["imported"]) == 2
    assert len(client.get(f"/v1/projects/{project}/conversations").json()["items"]) == 3
    again = client.post(f"/v1/imports/sessions/{token}/commit", json={
        "selectedIndexes": [0,129], "projectId": project,
    }).json()
    assert len(again["skipped"]) == 2 and not again["imported"]
    assert not app.state.workspace_store.context_items(sibling,user_id="local-user")
    assert client.delete(f"/v1/imports/sessions/{token}").status_code == 200
    assert client.get(f"/v1/imports/sessions/{token}").status_code == 404


def test_archive_rejects_zip_slip_ambiguous_and_oversize(tmp_path):
    _, client, _, _ = _setup(tmp_path)
    for contents in [
        {"../conversations.json": b"[]"},
        {"conversations.json": b"[]", "other/conversations.json": b"[]"},
        {"conversations.json": b"Q" * 48_000_001},
    ]:
        response = client.post(
            "/v1/imports/upload?provider=chatgpt&filename=big.zip",
            content=_zip(contents),
        )
        assert response.status_code == 400, response.text
    assert client.post(
        "/v1/imports/upload?provider=chatgpt&filename=big.zip",
        content=b"not zip",
    ).status_code == 400
    assert client.post(
        "/v1/imports/upload?provider=chatgpt&filename=bad.txt",
        content=b"hello",
    ).status_code == 400


def test_memory_review_requires_owner_action_and_skips_sensitive_text(tmp_path):
    app, client, project, sibling = _setup(tmp_path)
    records = [
        _chat(1, "프로젝트는 FastAPI로 개발하기로 결정했어"),
        _chat(2, "우리 프로젝트 API_KEY=sk-testsecret 사용"),
        _chat(3, "오늘 날씨가 어때?"),
    ]
    stage = client.post(
        "/v1/imports/upload?provider=chatgpt&filename=export.zip",
        content=_zip({"conversations.json":json.dumps(records,ensure_ascii=False).encode()}),
    ).json()
    client.post(f"/v1/imports/sessions/{stage['sessionId']}/commit",json={
        "selectedIndexes":[0,1,2], "projectId":project,
    })
    path = f"/v1/imports/projects/{project}/memory-candidates"
    candidates = client.get(path)
    assert candidates.status_code == 200
    items = candidates.json()["items"]
    assert len(items) == 1
    candidate = items[0]
    assert candidate["method"] == "local-heuristic"
    assert app.state.workspace_store.list_memories(project,user_id="local-user") == []
    assert app.state.workspace_store.context_items(sibling,user_id="local-user") == []

    msg_id = candidate["sourceMessageId"]
    review_url = f"{path}/{msg_id}/review"
    assert client.post(
        review_url,json={"decision":"approve","content":"FastAPI 사용"},
        headers={"X-EEEE-User-Id":"intruder"},
    ).status_code in {403,404}
    approved = client.post(
        review_url,json={"decision":"approve","content":"백엔드는 FastAPI를 사용"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["memoryId"]
    assert client.get(path).json()["items"] == []
    assert "백엔드는 FastAPI" in str(app.state.workspace_store.context_items(
        sibling,user_id="local-user"
    ))
    assert client.post(
        review_url,json={"decision":"approve","content":"다른 기억"},
    ).status_code == 409


def test_rejected_memory_candidate_never_becomes_shared_memory(tmp_path):
    app, client, project, sibling = _setup(tmp_path)
    stage = client.post(
        "/v1/imports/upload?provider=chatgpt&filename=archive.json",
        content=json.dumps([_chat(1)],ensure_ascii=False).encode(),
    ).json()
    client.post(f"/v1/imports/sessions/{stage['sessionId']}/commit",json={
        "selectedIndexes":[0], "projectId":project,
    })
    path = f"/v1/imports/projects/{project}/memory-candidates"
    item = client.get(path).json()["items"][0]
    response = client.post(f"{path}/{item['sourceMessageId']}/review",json={
        "decision":"dismiss",
    })
    assert response.status_code == 200
    assert client.get(path).json()["items"] == []
    assert not app.state.workspace_store.list_memories(project,user_id="local-user")
    assert app.state.workspace_store.context_items(sibling,user_id="local-user") == []
