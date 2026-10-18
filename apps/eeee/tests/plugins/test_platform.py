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
        self.raise_health = False
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
        if self.raise_health:
            raise ConnectionError("provider unavailable")
        return ConnectorHealth(
            status="healthy" if self.healthy else "unavailable",
            code="healthy" if self.healthy else "provider_unavailable",
            reason="ok" if self.healthy else "provider down",
        )

    def invoke(self, connection, action, value):
        return {"status": "completed", "action": action, "value": value}


class GenericFakeConnector(FakeConnector):
    plugin_id = "gmail"


class RefreshingFakeConnector(GenericFakeConnector):
    def connect(self, user_id, credential, approved_permissions):
        return ConnectorConnection(
            user_id=user_id, plugin_id=self.plugin_id,
            approved_permissions=frozenset(approved_permissions),
            client={"access_token": credential["access_token"]},
        )

    def health(self, connection):
        if connection.client["access_token"] == "old":
            return ConnectorHealth(
                status="unhealthy", code="reauthentication_required", reason="expired"
            )
        return ConnectorHealth(status="healthy", code="healthy", reason="ok")

    def refresh_credential(self, credential):
        assert credential["refresh_token"] == "refresh"
        return {"access_token": "new", "refresh_token": "refresh"}


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


def test_platform_refreshes_expired_provider_credential_and_persists_new_token(tmp_path) -> None:
    connector = RefreshingFakeConnector()
    credentials = MemoryCredentialStore()
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    platform = PluginPlatformService(
        store, credentials=credentials, connectors={"gmail": connector},
    )
    platform.install("gmail")
    platform.connect(
        "user-a", "gmail", {"mail.read"},
        {"access_token": "new", "refresh_token": "refresh"}, None,
    )
    connection = platform.connections.get("user-a", "gmail")
    replacement = credentials.put(
        "user-a", "gmail", '{"access_token": "old", "refresh_token": "refresh"}'
    )
    platform.connections.save(connection.model_copy(update={"credential_ref": replacement}))
    credentials.delete(connection.credential_ref)

    health = platform.health("user-a", "gmail")

    assert health.status == "healthy"
    refreshed = platform.connections.get("user-a", "gmail")
    assert refreshed.status == "connected"
    assert credentials.get(refreshed.credential_ref) == '{"access_token": "new", "refresh_token": "refresh"}'
    assert platform.capabilities("user-a")[0].id == "plugin:gmail:mail.list"


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


def test_health_failure_is_reported_without_raising_or_exposing_capability(tmp_path) -> None:
    connector = FakeConnector()
    platform = _platform(tmp_path, connector)
    platform.install("notion")
    platform.connect("user-a", "notion", {"pages.read"}, {"token": "secret"}, None)
    connector.raise_health = True

    health = platform.health("user-a", "notion")

    assert health.status == "unavailable"
    assert health.code == "provider_unavailable"
    connection = platform.connections.get("user-a", "notion")
    assert connection.status == "failed"
    assert connection.last_error == "provider_unavailable"
    assert platform.capabilities("user-a") == []


def test_unconfigured_catalog_connector_can_install_but_cannot_connect(tmp_path) -> None:
    platform = _platform(tmp_path, FakeConnector())

    assert platform.status("gmail", "user-a") == "not_installed"
    assert platform.install("gmail").status == "available"
    assert platform.status("gmail", "user-a") == "installed"
    with pytest.raises(RuntimeError, match="connector is unavailable"):
        platform.begin_oauth("user-a", "gmail", {"mail.read"}, None)


def test_chat_history_install_copies_only_the_plugin_and_exposes_launch_info(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    platform = PluginPlatformService(
        store,
        plugin_install_root=tmp_path / "plugins",
        connectors={},
    )

    installed = platform.install("eeee-chat-history")

    assert installed.status == "connected"
    assert platform.status("eeee-chat-history") == "connected"
    launch = platform.launch_info("eeee-chat-history")
    assert launch["pluginId"] == "eeee-chat-history"
    assert str(launch["entrypoint"]).endswith("eeee_chat_history\\main.py")
    assert (tmp_path / "plugins" / "eeee_chat_history" / "manifest.json").is_file()

    platform.uninstall("eeee-chat-history")
    assert not (tmp_path / "plugins" / "eeee_chat_history").exists()


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


def test_platform_extracts_natural_language_input_and_requires_send_approval(tmp_path) -> None:
    connector = GenericFakeConnector()
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    platform = PluginPlatformService(
        store, credentials=MemoryCredentialStore(), connectors={"gmail": connector}
    )
    platform.install("gmail")
    platform.connect(
        "user-a", "gmail", {"mail.read", "mail.send"},
        {"access_token": "secret"}, "Work",
    )

    waiting = platform.invoke(
        "user-a", "plugin:gmail:mail.send",
        {"text": "s25011@gsm.hs.kr 에 test라는 메일 보내"},
    )

    assert waiting.status.value == "awaiting_approval"
    assert waiting.required_approval is True
    assert waiting.side_effect_level.value == "external"
    assert waiting.output["status"] == "awaiting_approval"
    assert waiting.input["to"] == "s25011@gsm.hs.kr"
    assert waiting.input["subject"] == "test"

    completed = platform.invoke(
        "user-a", "plugin:gmail:mail.send",
        {"text": "s25011@gsm.hs.kr 에 test라는 메일 보내", "approved": True},
    )

    assert completed.status.value == "completed"
    assert completed.approval_state.value == "approved"
    assert completed.input["body"] == "test"


def test_platform_returns_blocked_envelope_for_incomplete_natural_language_send(tmp_path) -> None:
    connector = GenericFakeConnector()
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    platform = PluginPlatformService(
        store, credentials=MemoryCredentialStore(), connectors={"gmail": connector}
    )
    platform.install("gmail")
    platform.connect(
        "user-a", "gmail", {"mail.send"}, {"access_token": "secret"}, "Work"
    )

    result = platform.invoke(
        "user-a", "plugin:gmail:mail.send",
        {"text": "제목만 있는 메일 보내", "approved": True},
    )

    assert result.status.value == "blocked"
    assert result.error is not None
    assert "받는 사람" in result.error.message


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
