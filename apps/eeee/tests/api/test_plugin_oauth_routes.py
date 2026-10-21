from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plugins.connectors import ConnectorConnection, ConnectorHealth
from app.plugins.credentials import MemoryCredentialStore
from app.plugins.oauth import OAuthBroker, OAuthProviderConfig


class HealthyConnector:
    plugin_id = "notion"

    def connect(self, user_id, credential, approved_permissions):
        return ConnectorConnection(
            user_id=user_id, plugin_id=self.plugin_id,
            approved_permissions=frozenset(approved_permissions), client=object(),
        )

    def disconnect(self, connection):
        return None

    def health(self, connection):
        return ConnectorHealth(status="healthy", code="healthy", reason="ok")

    def invoke(self, connection, action, value):
        return {"status": "completed"}


class UnavailableConnector(HealthyConnector):
    def health(self, connection):
        return ConnectorHealth(status="unavailable", code="provider_unavailable", reason="down")


class FakeOAuthTransport:
    def exchange_code(self, config, *, code, code_verifier, redirect_uri):
        return {"access_token": "oauth-secret", "parentPageId": "page-id"}


def _application(tmp_path, connector=None):
    application = create_app(
        Settings(
            data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces",
            claim_latch_auto_start=False,
        ),
        oauth_broker=OAuthBroker(FakeOAuthTransport()),
        oauth_configs={
            "notion": OAuthProviderConfig(
                authorizationEndpoint="https://provider.example/authorize",
                tokenEndpoint="https://provider.example/token",
                clientId="public-client",
                scopes=["pages.read"],
                scopeByPermission={"pages.read": ["pages.read"]},
            )
        },
    )
    application.state.plugin_platform.credentials = MemoryCredentialStore()
    application.state.plugin_platform.connectors["notion"] = connector or HealthyConnector()
    return application


def test_oauth_start_and_callback_connect_user_without_returning_tokens(tmp_path) -> None:
    client = TestClient(_application(tmp_path))
    assert client.post("/api/plugins/notion/install").status_code == 200

    started = client.post(
        "/api/plugins/notion/oauth/start",
        headers={"X-EEEE-User-Id": "user-a"},
        json={"approvedPermissions": ["pages.read"], "accountLabel": "Work"},
    )
    assert started.status_code == 200
    body = started.json()
    assert body["pluginId"] == "notion"
    assert "oauth-secret" not in started.text
    pending = client.get(
        "/api/plugins/notion/connection",
        headers={"X-EEEE-User-Id": "user-a"},
    )
    assert pending.json()["status"] == "connecting"
    query = parse_qs(urlparse(body["authorizationUrl"]).query)
    state = query["state"][0]
    assert "code_verifier" not in body["authorizationUrl"]

    callback = client.get(
        "/api/plugins/notion/oauth/callback",
        params={"state": state, "code": "authorization-code"},
    )
    assert callback.status_code == 200
    assert callback.headers["content-type"].startswith("text/html")
    assert "연결" in callback.text
    assert "oauth-secret" not in callback.text

    oauth_status = client.get(
        "/api/plugins/notion/oauth/status",
        params={"state": state},
        headers={"X-EEEE-User-Id": "user-a"},
    )
    assert oauth_status.status_code == 200
    assert oauth_status.json() == {
        "pluginId": "notion", "state": "completed", "error": None
    }

    connection = client.get(
        "/api/plugins/notion/connection", headers={"X-EEEE-User-Id": "user-a"}
    )
    assert connection.json()["status"] == "connected"
    assert connection.json()["accountLabel"] == "Work"


def test_oauth_requires_installation_and_configuration(tmp_path) -> None:
    application = _application(tmp_path)
    client = TestClient(application)

    not_installed = client.post(
        "/api/plugins/notion/oauth/start",
        headers={"X-EEEE-User-Id": "user-a"},
        json={"approvedPermissions": ["pages.read"]},
    )
    assert not_installed.status_code == 409

    no_config = create_app(
        Settings(
            data_dir=tmp_path / "other-data", workspace_root=tmp_path / "other-workspaces",
            claim_latch_auto_start=False,
        )
    )
    no_config_client = TestClient(no_config)
    assert no_config_client.post("/api/plugins/notion/install").status_code == 200
    response = no_config_client.post(
        "/api/plugins/notion/oauth/start",
        headers={"X-EEEE-User-Id": "user-a"},
        json={"approvedPermissions": ["pages.read"]},
    )
    assert response.status_code == 503


def test_oauth_start_maps_permission_and_connector_failures_to_actionable_statuses(tmp_path) -> None:
    application = _application(tmp_path)
    client = TestClient(application)
    assert client.post("/api/plugins/notion/install").status_code == 200

    forbidden = client.post(
        "/api/plugins/notion/oauth/start",
        headers={"X-EEEE-User-Id": "user-a"},
        json={"approvedPermissions": ["not-a-permission"]},
    )
    assert forbidden.status_code == 403

    application.state.plugin_platform.connectors.pop("notion")
    unavailable = client.post(
        "/api/plugins/notion/oauth/start",
        headers={"X-EEEE-User-Id": "user-a"},
        json={"approvedPermissions": ["pages.read"]},
    )
    assert unavailable.status_code == 409


def test_oauth_start_rejects_notion_write_without_read_dependency(tmp_path) -> None:
    client = TestClient(_application(tmp_path))
    assert client.post("/api/plugins/notion/install").status_code == 200

    response = client.post(
        "/api/plugins/notion/oauth/start",
        headers={"X-EEEE-User-Id": "user-a"},
        json={"approvedPermissions": ["pages.write"]},
    )

    assert response.status_code == 403
    assert "pages.read" in response.json()["detail"]
    assert client.get(
        "/api/plugins/notion/connection", headers={"X-EEEE-User-Id": "user-a"}
    ).json()["status"] == "awaiting_authentication"


def test_oauth_cancel_returns_friendly_page_and_terminal_status(tmp_path) -> None:
    client = TestClient(_application(tmp_path))
    assert client.post("/api/plugins/notion/install").status_code == 200
    started = client.post(
        "/api/plugins/notion/oauth/start",
        headers={"X-EEEE-User-Id": "user-a"},
        json={"approvedPermissions": ["pages.read"]},
    )
    state = parse_qs(urlparse(started.json()["authorizationUrl"]).query)["state"][0]

    callback = client.get(
        "/api/plugins/notion/oauth/callback",
        params={"state": state, "error": "access_denied"},
    )
    assert callback.status_code == 200
    assert callback.headers["content-type"].startswith("text/html")
    assert "취소" in callback.text
    assert client.get(
        "/api/plugins/notion/oauth/status", params={"state": state}
    ).json()["state"] == "cancelled"
    assert client.get(
        "/api/plugins/notion/connection", headers={"X-EEEE-User-Id": "user-a"}
    ).json()["status"] == "failed"


def test_oauth_callback_reports_connector_health_failure(tmp_path) -> None:
    client = TestClient(_application(tmp_path, UnavailableConnector()))
    assert client.post("/api/plugins/notion/install").status_code == 200
    started = client.post(
        "/api/plugins/notion/oauth/start",
        headers={"X-EEEE-User-Id": "user-a"},
        json={"approvedPermissions": ["pages.read"]},
    )
    state = parse_qs(urlparse(started.json()["authorizationUrl"]).query)["state"][0]

    callback = client.get(
        "/api/plugins/notion/oauth/callback",
        params={"state": state, "code": "authorization-code"},
    )

    assert callback.status_code == 409
    assert "연결 실패" in callback.text
    assert client.get("/api/plugins/notion/oauth/status", params={"state": state}).json() == {
        "pluginId": "notion", "state": "failed", "error": "oauth_connection_failed"
    }
