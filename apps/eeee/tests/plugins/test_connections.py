from datetime import datetime, timezone

from app.plugins.connections import PluginConnection
from app.plugins.credentials import MemoryCredentialStore
from app.runtime.store import PluginConnectionStore, PluginInstallationStore
from app.storage.sqlite import SQLiteStore


def _store(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    return store


def test_optional_installation_persists_across_store_restart(tmp_path) -> None:
    store = _store(tmp_path)
    installations = PluginInstallationStore(store)

    created = installations.install("notion", "1.0.0")
    assert created.plugin_id == "notion"
    assert installations.is_installed("notion") is True

    reopened = PluginInstallationStore(SQLiteStore(store.path))
    assert reopened.is_installed("notion") is True
    assert reopened.get("notion").version == "1.0.0"


def test_user_connections_are_isolated_and_store_only_opaque_credential_refs(tmp_path) -> None:
    store = _store(tmp_path)
    installations = PluginInstallationStore(store)
    installations.install("notion", "1.0.0")
    credentials = MemoryCredentialStore()
    reference = credentials.put("user-a", "notion", "token-a-secret")
    connections = PluginConnectionStore(store)
    connection = PluginConnection(
        user_id="user-a", plugin_id="notion", status="connected",
        approved_permissions=["pages.read"], credential_ref=reference,
        account_label="A workspace", last_health="healthy", last_error=None,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

    connections.save(connection)

    assert connections.get("user-a", "notion").approved_permissions == ["pages.read"]
    assert connections.list("user-b") == []
    assert "token-a-secret" not in connections.get("user-a", "notion").model_dump_json()
    assert credentials.get(reference) == "token-a-secret"


def test_disconnect_removes_connection_and_credential_reference(tmp_path) -> None:
    store = _store(tmp_path)
    credentials = MemoryCredentialStore()
    reference = credentials.put("user-a", "notion", "token-a-secret")
    connections = PluginConnectionStore(store)
    connections.save(PluginConnection(
        user_id="user-a", plugin_id="notion", status="connected",
        approved_permissions=["pages.read"], credential_ref=reference,
        account_label=None, last_health="healthy", last_error=None,
        updated_at=datetime.now(timezone.utc).isoformat(),
    ))

    connections.remove("user-a", "notion")
    credentials.delete(reference)

    assert connections.list("user-a") == []
    assert credentials.get(reference) is None
