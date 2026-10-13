from datetime import datetime, timezone

import pytest

from app.plugins.connectors import ConnectorConnection, ConnectorHealth
from app.plugins.credentials import MemoryCredentialStore
from app.plugins.platform import PluginPlatformService
from app.storage.sqlite import SQLiteStore
from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


class FakeConnector:
    plugin_id = "notion"

    def __init__(self, healthy: bool = True):
        self.healthy = healthy
        self.connections = []

    def connect(self, user_id, credential, approved_permissions):
        self.connections.append((user_id, dict(credential), set(approved_permissions)))
        return ConnectorConnection(
            user_id=user_id, plugin_id=self.plugin_id,
            approved_permissions=frozenset(approved_permissions), client=object(),
        )

    def disconnect(self, connection):
        return None

    def health(self, connection):
        return ConnectorHealth(
            status="healthy" if self.healthy else "unavailable",
            code="healthy" if self.healthy else "provider_unavailable",
            reason="ok" if self.healthy else "provider down",
        )

    def invoke(self, connection, action, value):
        return {"status": "completed", "action": action, "value": value}


class GenericFakeConnector(FakeConnector):
    plugin_id = "gmail"


def _platform(tmp_path, connector):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    return PluginPlatformService(
        store, credentials=MemoryCredentialStore(), connectors={"notion": connector}
    )


def test_platform_hides_optional_capability_until_install_connect_and_health(tmp_path) -> None:
    connector = FakeConnector()
    platform = _platform(tmp_path, connector)

    assert platform.capabilities("user-a") == []
    assert platform.install("notion").status == "available"
    assert platform.capabilities("user-a") == []

    connected = platform.connect(
        "user-a", "notion", {"pages.read"}, {"token": "secret"}, "A workspace"
    )

    assert connected.status == "connected"
    assert [item.id for item in platform.capabilities("user-a")] == ["plugin:notion:pages"]
    assert "secret" not in connected.model_dump_json()


def test_platform_isolates_users_and_disconnect_removes_capability(tmp_path) -> None:
    platform = _platform(tmp_path, FakeConnector())
    platform.install("notion")
    platform.connect("user-a", "notion", {"pages.read"}, {"token": "secret-a"}, None)

    assert platform.capabilities("user-b") == []
    platform.disconnect("user-a", "notion")
    assert platform.capabilities("user-a") == []


def test_platform_marks_provider_failure_and_does_not_expose_capability(tmp_path) -> None:
    connector = FakeConnector(healthy=False)
    credentials = MemoryCredentialStore()
    platform = PluginPlatformService(
        SQLiteStore(tmp_path / "state.sqlite3"),
        credentials=credentials, connectors={"notion": connector},
    )
    platform.connections.store.init()
    platform.install("notion")

    failed = platform.connect("user-a", "notion", {"pages.read"}, {"token": "secret"}, None)

    assert failed.status == "failed"
    assert failed.last_error == "provider_unavailable"
    assert platform.connections.get("user-a", "notion").credential_ref is None
    assert credentials._values == {}
    assert platform.capabilities("user-a") == []


def test_failed_reconnect_keeps_existing_healthy_credential(tmp_path) -> None:
    connector = FakeConnector()
    credentials = MemoryCredentialStore()
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    platform = PluginPlatformService(
        store, credentials=credentials, connectors={"notion": connector}
    )
    platform.install("notion")
    connected = platform.connect(
        "user-a", "notion", {"pages.read"}, {"token": "old-secret"}, None
    )
    old_connection = platform.connections.get("user-a", "notion")
    connector.healthy = False

    retried = platform.connect(
        "user-a", "notion", {"pages.read"}, {"token": "new-secret"}, None
    )

    assert connected.status == "connected"
    assert retried.status == "connected"
    assert platform.connections.get("user-a", "notion").credential_ref == old_connection.credential_ref
    assert credentials.get(old_connection.credential_ref) == '{"token": "old-secret"}'
    assert all("new-secret" not in value for value in credentials._values.values())


def test_unconfigured_catalog_connector_is_disabled_and_not_installable(tmp_path) -> None:
    platform = _platform(tmp_path, FakeConnector())

    assert platform.status("gmail", "user-a") == "disabled"
    with pytest.raises(RuntimeError, match="connector is unavailable"):
        platform.install("gmail")


def test_connected_first_party_provider_projects_action_capabilities_and_invokes_action(tmp_path) -> None:
    connector = GenericFakeConnector()
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    platform = PluginPlatformService(
        store, credentials=MemoryCredentialStore(), connectors={"gmail": connector}
    )
    platform.install("gmail")
    platform.connect("user-a", "gmail", {"mail.read"}, {"access_token": "secret"}, "Work")

    capabilities = platform.capabilities("user-a")

    assert [item.id for item in capabilities] == ["plugin:gmail:mail.list"]
    result = platform.invoke("user-a", "plugin:gmail:mail.list", {"query": "unread"})
    assert result.status == "completed"
    assert result.output["action"] == "mail.list"


def test_application_distinguishes_optional_installation_from_connection_requirement(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces",
        claim_latch_auto_start=False,
    )
    application = create_app(settings)
    client = TestClient(application)

    not_installed = client.post("/api/assistant/route", json={"text": "노션에 회의록 저장해줘"})
    assert not_installed.status_code == 200
    assert "설치" in (not_installed.json().get("suggested_action") or "")

    application.state.plugin_platform.install("notion")
    awaiting_connection = client.post("/api/assistant/route", json={"text": "노션에 회의록 저장해줘"})
    assert awaiting_connection.status_code == 200
    assert "연결" in (awaiting_connection.json().get("suggested_action") or "")
