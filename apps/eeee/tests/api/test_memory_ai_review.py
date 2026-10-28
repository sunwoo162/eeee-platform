"""Consent-first, owner-scoped AI analysis of imported memory candidates."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class FakeModel:
    model = "stub-review-model"

    def __init__(self, report: dict | str) -> None:
        self.report = report
        self.calls: list[list[dict]] = []

    def stream(self, messages, **kwargs):
        self.calls.append(messages)
        payload = self.report if isinstance(self.report, str) else json.dumps(self.report)
        yield payload[:len(payload)//2]
        yield payload[len(payload)//2:]


def _setup(tmp_path):
    app = create_app(Settings(
        data_dir=tmp_path / "data", workspace_root=tmp_path / "work",
    ))
    client = TestClient(app)
    wid = client.post("/v1/workspaces", json={"kind": "personal", "name": "Mine"}).json()["id"]
    pid = client.post(f"/v1/workspaces/{wid}/projects", json={"name": "Example"}).json()["id"]
    sibling = client.post(
        f"/v1/projects/{pid}/conversations",json={"title":"Sibling"},
    ).json()["id"]
    text = "프로젝트는 FastAPI 대신 Flask를 사용하기로 결정했어"
    source = [{
        "id": "foreign-1", "title": "Old design",
        "current_node": "one",
        "mapping": {
            "one": {"parent": None, "message": {
                "author": {"role": "user"},
                "content": {"content_type": "text", "parts": [text]},
            }},
        },
    }]
    saved = client.post("/v1/imports/commit", json={
        "provider":"chatgpt", "content":json.dumps(source,ensure_ascii=False),
        "selectedIndexes":[0], "projectId":pid,
    })
    assert saved.status_code == 200, saved.text
    item = client.get(f"/v1/imports/projects/{pid}/memory-candidates").json()["items"][0]
    return app, client, pid, sibling, item


def _ai(app, report):
    hub = app.state.conversation_service.provider_hub
    fake = FakeModel(report)
    hub.available["gpt"] = True
    hub.providers["gpt"] = fake
    return fake


def _analyze(client, pid, item, **body):
    return client.post(
        f"/v1/imports/projects/{pid}/memory-candidates/{item['sourceMessageId']}/analyze",
        json={"provider":"gpt", "consent": True, **body},
    )


def test_ai_analysis_requires_opt_in_and_handles_conflict_before_review(tmp_path):
    app, client, pid, sibling, item = _setup(tmp_path)
    approved = client.post(f"/v1/projects/{pid}/memories",json={
        "content":"백엔드는 FastAPI로 개발한다",
    })
    assert approved.status_code == 201, approved.text
    existing_id = approved.json()["id"]
    fake = _ai(app, {
        "verdict": "conflict",
        "suggestedText": "백엔드를 Flask로 변경하기로 결정했다",
        "reason": "Previously approved FastAPI conflicts with Flask choice",
        "relatedMemoryIds": [existing_id],
    })
    denied = _analyze(client, pid, item, consent=False)
    assert denied.status_code == 403
    no_access = _analyze(
        client, pid, item,
        # headers are passed below in a separate call
    )
    assert no_access.status_code == 200, no_access.text
    assert len(fake.calls) == 1
    sent = json.dumps(fake.calls[0],ensure_ascii=False)
    assert "FastAPI" in sent and "Flask" in sent

    path = f"/v1/imports/projects/{pid}/memory-candidates"
    refreshed = client.get(path).json()["items"][0]
    assert refreshed["analysis"]["verdict"] == "conflict"
    assert refreshed["analysis"]["relatedMemories"][0]["id"] == existing_id
    assert len(app.state.workspace_store.list_memories(pid,user_id="local-user")) == 1
    assert "Flask" not in str(app.state.workspace_store.context_items(
        sibling,user_id="local-user"
    ))

    review = f"{path}/{item['sourceMessageId']}/review"
    blocked = client.post(review,json={
        "decision":"approve","content":"Flask를 사용하기로 한다",
    })
    assert blocked.status_code == 409
    approved_new = client.post(review,json={
        "decision":"approve","content":"Flask를 사용하기로 한다",
        "acknowledgedRisk":True,
    })
    assert approved_new.status_code == 200, approved_new.text
    assert len(app.state.workspace_store.list_memories(pid,user_id="local-user")) == 2


def test_unavailable_and_malicious_response_do_not_write_or_send(tmp_path):
    app, client, pid, _, item = _setup(tmp_path)
    path = f"/v1/imports/projects/{pid}/memory-candidates"
    no_provider = _analyze(client,pid,item)
    assert no_provider.status_code == 409
    fake = _ai(app, {
        "verdict":"new", "suggestedText":"sk-testsecret",
        "reason":"looks fine", "relatedMemoryIds": [],
    })
    rejected = _analyze(client,pid,item)
    assert rejected.status_code == 409
    assert len(fake.calls) == 1
    assert client.get(path).json()["items"][0]["analysis"] is None
    assert not app.state.workspace_store.list_memories(pid,user_id="local-user")
    # Unsupported reference IDs are also rejected.
    fake.report = {
        "verdict":"conflict","suggestedText":"Use Flask",
        "reason":"Invalid relation","relatedMemoryIds":["other-project-memory"],
    }
    assert _analyze(client,pid,item).status_code == 409
    assert client.get(path).json()["items"][0]["analysis"] is None


def test_exact_duplicate_blocked_even_if_ai_says_new(tmp_path):
    app, client, pid, _, item = _setup(tmp_path)
    assert client.post(f"/v1/projects/{pid}/memories",json={
        "content":"Flask 사용",
    }).status_code == 201
    _ai(app, {"verdict":"new","suggestedText":"Flask 사용",
              "reason":"A new preference","relatedMemoryIds":[]})
    assert _analyze(client,pid,item).status_code == 200
    path=f"/v1/imports/projects/{pid}/memory-candidates/{item['sourceMessageId']}/review"
    response=client.post(path,json={"decision":"approve","content":"  Flask   사용  "})
    assert response.status_code == 409
    response=client.post(path,json={"decision":"approve","content":"Flask 사용",
                                   "acknowledgedRisk":True})
    assert response.status_code == 409
    assert len(app.state.workspace_store.list_memories(pid,user_id="local-user")) == 1


def test_invalid_model_json_no_approval_and_scoped_access(tmp_path):
    app, client, pid, _, item = _setup(tmp_path)
    fake = _ai(app, "This is not JSON")
    assert _analyze(client,pid,item).status_code == 409
    assert len(fake.calls) == 1
    path=f"/v1/imports/projects/{pid}/memory-candidates/{item['sourceMessageId']}/analyze"
    forbidden=client.post(path,json={"provider":"gpt","consent":True},
                          headers={"X-EEEE-User-Id":"intruder"})
    assert forbidden.status_code in {403,404}
    assert len(fake.calls) == 1
    assert client.get(f"/v1/imports/projects/{pid}/memory-candidates",
                      headers={"X-EEEE-User-Id":"intruder"}).status_code in {403,404}


def test_memory_change_invalidates_previous_ai_review(tmp_path):
    app, client, pid, _, item = _setup(tmp_path)
    _ai(app, {
        "verdict":"new", "suggestedText":"Flask를 사용",
        "reason":"Project decision", "relatedMemoryIds":[],
    })
    assert _analyze(client,pid,item).status_code == 200
    # Another authorized action changes the approved memory set.
    assert client.post(f"/v1/projects/{pid}/memories",json={
        "content":"API 서버는 Django 사용",
    }).status_code == 201
    review_path=f"/v1/imports/projects/{pid}/memory-candidates/{item['sourceMessageId']}/review"
    assert client.post(review_path,json={
        "decision":"approve","content":"Flask를 사용", "acknowledgedRisk":True,
    }).status_code == 409
    assert _analyze(client,pid,item).status_code == 200
    assert client.post(review_path,json={
        "decision":"approve","content":"Flask를 사용",
    }).status_code == 200


def test_approved_memory_edit_invalidates_ai_analysis(tmp_path):
    app, client, pid, _, item = _setup(tmp_path)
    memory = client.post(f"/v1/projects/{pid}/memories", json={
        "content":"Use FastAPI",
    }).json()["id"]
    fake = _ai(app, {
        "verdict":"conflict",
        "suggestedText":"Use Flask",
        "reason":"Contradicts the prior backend choice",
        "relatedMemoryIds":[memory],
    })
    assert _analyze(client, pid, item).status_code == 200
    assert fake.calls
    changed=client.put(f"/v1/projects/{pid}/memories/{memory}",json={
        "content":"Use Django","expectedVersion":1,
    })
    assert changed.status_code==200,changed.text
    review=f"/v1/imports/projects/{pid}/memory-candidates/{item['sourceMessageId']}/review"
    assert client.post(review,json={
        "decision":"approve","content":"Use Flask","acknowledgedRisk":True,
    }).status_code==409
    assert _analyze(client,pid,item).status_code==200
    assert client.post(review,json={
        "decision":"approve","content":"Use Flask","acknowledgedRisk":True,
    }).status_code==200
