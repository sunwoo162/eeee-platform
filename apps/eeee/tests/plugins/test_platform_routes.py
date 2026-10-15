from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plugins.connectors import ConnectorConnection, ConnectorHealth
from app.plugins.credentials import MemoryCredentialStore


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


def _application(tmp_path):
    application = create_app(Settings(
        data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces",
        claim_latch_auto_start=False,
    ))
    application.state.plugin_platform.credentials = MemoryCredentialStore()
    application.state.plugin_platform.connectors["notion"] = HealthyConnector()
    return application


def test_catalog_install_connect_and_disconnect_are_redacted_and_user_scoped(tmp_path) -> None:
    client = TestClient(_application(tmp_path))

    catalog = client.get("/api/plugins/catalog").json()
    notion = next(item for item in catalog if item["id"] == "notion")
    assert notion["status"] == "not_installed"
    assert notion["nextAction"] == "install"
    assert [field["key"] for field in notion["credentialFields"]] == ["token", "parentPageId"]
    assert [item["defaultApproved"] for item in notion["permissionDetails"]] == [True, False]

    installed = client.post("/api/plugins/notion/install")
    assert installed.status_code == 200
    assert installed.json()["status"] == "available"

    awaiting = client.get("/api/plugins/notion/connection")
    assert awaiting.status_code == 200
    assert awaiting.json()["status"] == "awaiting_authentication"

    connected = client.post(
        "/api/plugins/notion/connect",
        headers={"X-EEEE-User-Id": "user-a"},
        json={
            "approvedPermissions": ["pages.read"],
            "credential": {"token": "secret-token", "parentPageId": "page-id"},
            "accountLabel": "Work",
        },
    )
    assert connected.status_code == 200
    body = connected.json()
    assert body["status"] == "connected"
    assert "secret-token" not in connected.text

    paused = client.post("/api/plugins/notion/pause", headers={"X-EEEE-User-Id": "user-a"})
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    resumed = client.post("/api/plugins/notion/resume", headers={"X-EEEE-User-Id": "user-a"})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "connected"

    other_user = client.get(
        "/api/plugins/notion/connection", headers={"X-EEEE-User-Id": "user-b"}
    )
    assert other_user.json()["status"] == "awaiting_authentication"

    disconnected = client.post("/api/plugins/notion/disconnect", headers={"X-EEEE-User-Id": "user-a"})
    assert disconnected.status_code == 200
    assert disconnected.json()["status"] == "awaiting_authentication"


def test_install_is_local_and_does_not_require_provider_connector(tmp_path) -> None:
    client = TestClient(_application(tmp_path))

    installed = client.post("/api/plugins/gmail/install")

    assert installed.status_code == 200
    assert installed.json() == {
        "pluginId": "gmail",
        "version": "1.0.0",
        "status": "available",
    }

    catalog = client.get("/api/plugins/catalog").json()
    gmail = next(item for item in catalog if item["id"] == "gmail")
    assert gmail["status"] == "installed"
    assert gmail["nextAction"] == "configure"


def test_chat_history_plugin_installs_and_exposes_a_separate_entrypoint(tmp_path) -> None:
    client = TestClient(_application(tmp_path))

    catalog = client.get("/api/plugins/catalog").json()
    chat_history = next(item for item in catalog if item["id"] == "eeee-chat-history")
    assert chat_history["authMode"] == "none"
    assert chat_history["status"] == "not_installed"
    assert chat_history["nextAction"] == "install"

    installed = client.post("/api/plugins/eeee-chat-history/install")
    assert installed.status_code == 200
    assert installed.json()["status"] == "connected"

    launch = client.get("/api/plugins/eeee-chat-history/launch")
    assert launch.status_code == 200
    assert launch.json()["pluginId"] == "eeee-chat-history"
    assert launch.json()["entrypoint"].endswith("eeee_chat_history\\main.py")


def test_malformed_user_scope_is_rejected(tmp_path) -> None:
    client = TestClient(_application(tmp_path))
    response = client.get(
        "/api/plugins/notion/connection", headers={"X-EEEE-User-Id": "../other-user"}
    )
    assert response.status_code == 400
