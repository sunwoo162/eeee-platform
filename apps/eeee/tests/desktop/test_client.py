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
            {
                "timeout": 180.0,
                "json": {
                    "text": "Make a project",
                    "workspace": "C:/work",
                    "conversationId": "desktop-default",
                },
            },
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


def test_assistant_route_keeps_the_desktop_conversation_id(monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(200, json={"status": "completed", "message": "응답"})

    monkeypatch.setattr(httpx, "request", request)

    PetApiClient("http://127.0.0.1:8123").route_assistant("이어서 해줘")

    assert requests[0][2]["json"]["conversationId"] == "desktop-default"


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


def test_client_supports_plugin_catalog_install_and_connection_lifecycle(monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        if url.endswith("/api/plugins/catalog"):
            return httpx.Response(200, json=[{"id": "notion", "status": "not_installed"}])
        if url.endswith("/api/plugins/notion/connection"):
            return httpx.Response(200, json={"pluginId": "notion", "status": "connected"})
        if url.endswith("/api/plugins/notion/oauth/start"):
            return httpx.Response(200, json={"pluginId": "notion", "authorizationUrl": "https://example.test/oauth"})
        return httpx.Response(200, json={"pluginId": "notion", "status": "available"})

    monkeypatch.setattr(httpx, "request", request)
    client = PetApiClient("http://127.0.0.1:8123")

    assert client.get_plugin_catalog() == [{"id": "notion", "status": "not_installed"}]
    assert client.install_plugin("notion")["status"] == "available"
    assert client.start_plugin_oauth("notion", ["pages.read"], "workspace")['authorizationUrl'] == "https://example.test/oauth"
    assert client.get_plugin_connection("notion")["status"] == "connected"
    assert client.disconnect_plugin("notion")["status"] == "available"

    assert requests == [
        ("GET", "http://127.0.0.1:8123/api/plugins/catalog", {"timeout": 5.0}),
        ("POST", "http://127.0.0.1:8123/api/plugins/notion/install", {"timeout": 5.0}),
        (
            "POST",
            "http://127.0.0.1:8123/api/plugins/notion/oauth/start",
            {
                "timeout": 5.0,
                "json": {"approvedPermissions": ["pages.read"], "accountLabel": "workspace"},
            },
        ),
        ("GET", "http://127.0.0.1:8123/api/plugins/notion/connection", {"timeout": 5.0}),
        ("POST", "http://127.0.0.1:8123/api/plugins/notion/disconnect", {"timeout": 5.0}),
    ]


def test_client_supports_plugin_pause_resume_and_uninstall(monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(200, json={"pluginId": "notion", "status": "paused"})

    monkeypatch.setattr(httpx, "request", request)
    client = PetApiClient("http://127.0.0.1:8123")

    assert client.pause_plugin("notion")["status"] == "paused"
    assert client.resume_plugin("notion")["status"] == "paused"
    assert client.uninstall_plugin("notion") == {"pluginId": "notion", "status": "paused"}

    assert requests == [
        ("POST", "http://127.0.0.1:8123/api/plugins/notion/pause", {"timeout": 5.0}),
        ("POST", "http://127.0.0.1:8123/api/plugins/notion/resume", {"timeout": 5.0}),
        ("DELETE", "http://127.0.0.1:8123/api/plugins/notion/install", {"timeout": 5.0}),
    ]


def test_client_can_read_oauth_terminal_status(monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(200, json={"pluginId": "notion", "state": "cancelled"})

    monkeypatch.setattr(httpx, "request", request)
    result = PetApiClient("http://127.0.0.1:8123").get_plugin_oauth_status("notion", "opaque-state")

    assert result["state"] == "cancelled"
    assert requests == [
        (
            "GET",
            "http://127.0.0.1:8123/api/plugins/notion/oauth/status",
            {"timeout": 5.0, "params": {"state": "opaque-state"}},
        )
    ]


def test_uninstall_accepts_the_api_204_response(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "request",
        lambda method, url, **kwargs: httpx.Response(204),
    )

    assert PetApiClient("http://127.0.0.1:8123").uninstall_plugin("notion") == {
        "pluginId": "notion", "status": "not_installed"
    }


def test_client_connect_plugin_sends_credential_without_logging_or_transforming_it(monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(200, json={"pluginId": "notion", "status": "connected"})

    monkeypatch.setattr(httpx, "request", request)
    result = PetApiClient("http://127.0.0.1:8123").connect_plugin(
        "notion", {"token": "secret-token"}, ["pages.read"]
    )

    assert result["status"] == "connected"
    assert requests[0] == (
        "POST",
        "http://127.0.0.1:8123/api/plugins/notion/connect",
        {
            "timeout": 5.0,
            "json": {
                "credential": {"token": "secret-token"},
                "approvedPermissions": ["pages.read"],
                "accountLabel": None,
            },
        },
    )
