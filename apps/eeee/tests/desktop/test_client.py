import httpx

from app.desktop.client import PetApiClient


def test_run_calls_task_run_endpoint(monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(200, json={"state": "awaiting_approval"})

    monkeypatch.setattr(httpx, "request", request)

    result = PetApiClient("http://127.0.0.1:8123").run("task-1")

    assert result == {"state": "awaiting_approval"}
    assert requests == [
        (
            "POST",
            "http://127.0.0.1:8123/projects/default/tasks/task-1/run",
            {"timeout": 5.0},
        )
    ]


def test_client_supports_canonical_eeee_desktop_contract(monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        if url.endswith("/api/desktop/state"):
            return httpx.Response(200, json={"status": "ok", "projectId": "project-1"})
        if url.endswith("/api/assistant/route"):
            return httpx.Response(200, json={"status": "ready", "project_id": "project-1"})
        if url.endswith("/api/desktop/pairing/code"):
            return httpx.Response(200, json={"code": "123456", "expiresAt": "later"})
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr(httpx, "request", request)
    client = PetApiClient("http://127.0.0.1:8123")

    assert client.get_desktop_state("project-1")["projectId"] == "project-1"
    assert client.route_assistant("Make a project", "C:/work") == {
        "status": "ready",
        "project_id": "project-1",
    }
    assert client.issue_pairing_code()["code"] == "123456"

    assert requests == [
        (
            "GET",
            "http://127.0.0.1:8123/api/desktop/state",
            {"timeout": 5.0, "params": {"projectId": "project-1"}},
        ),
        (
            "POST",
            "http://127.0.0.1:8123/api/assistant/route",
            {"timeout": 180.0, "json": {"text": "Make a project", "workspace": "C:/work"}},
        ),
        (
            "POST",
            "http://127.0.0.1:8123/api/desktop/pairing/code",
            {"timeout": 5.0},
        ),
    ]


def test_assistant_route_uses_long_timeout_for_web_ai(monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(200, json={"status": "completed", "message": "응답"})

    monkeypatch.setattr(httpx, "request", request)

    PetApiClient("http://127.0.0.1:8123").route_assistant("안녕")

    assert requests[0][2]["timeout"] == 180.0


def test_client_can_open_the_project_map(monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(200, json={"projectId": "project-1", "nodes": []})

    monkeypatch.setattr(httpx, "request", request)
    client = PetApiClient("http://127.0.0.1:8123")

    assert client.open_project("project-1")["projectId"] == "project-1"
    assert requests == [
        (
            "GET",
            "http://127.0.0.1:8123/api/projects/project-1/map",
            {"timeout": 5.0},
        )
    ]


def test_client_can_read_an_eeee_background_job(monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(200, json={"jobId": "assistant-job-1", "status": "running"})

    monkeypatch.setattr(httpx, "request", request)
    client = PetApiClient("http://127.0.0.1:8123")

    assert client.get_assistant_job("assistant-job-1")["status"] == "running"
    assert requests == [
        (
            "GET",
            "http://127.0.0.1:8123/api/assistant/jobs/assistant-job-1",
            {"timeout": 5.0},
        )
    ]
