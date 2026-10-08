import sys
from pathlib import Path

import pytest

from app.plugins.host import PluginHost
from app.plugins.manifest import discover_manifest
from app.plugins.models import PluginManifest
from app.storage.sqlite import SQLiteStore


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def host(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    manifest = discover_manifest(FIXTURES / "echo-plugin.json").model_copy(update={
        "command": [sys.executable, str(FIXTURES / "echo_plugin.py")],
    })
    result = PluginHost(store, allowed_scope_ids={"local.read"}, timeout_seconds=3)
    result.discover({**manifest.model_dump(mode="json", by_alias=True)})
    result.register(manifest)
    return result


def test_plugin_lifecycle_invokes_isolated_fixture_and_returns_envelope(host):
    connected = host.connect("echo", approval=True)
    assert connected.status == "connected"
    health = host.health("echo")
    assert health.status == "healthy"

    result = host.invoke("echo", "echo", {"message": "hello"})

    assert result.status.value == "completed"
    assert result.output == {"echo": {"message": "hello"}}
    assert result.capability_id == "plugin:echo"
    host.disconnect("echo")
    host.remove("echo")
    with pytest.raises(KeyError):
        host.health("echo")


def test_denied_approval_and_disconnected_invocation_are_truthful(host):
    with pytest.raises(PermissionError):
        host.connect("echo", approval=False)

    result = host.invoke("echo", "echo", {"message": "blocked"})

    assert result.status.value == "blocked"
    assert result.error is not None
    assert "connected" in result.error.message


def test_plugin_can_pause_and_resume_without_losing_registration(host):
    host.connect("echo", approval=True)

    paused = host.pause("echo")
    assert paused.status == "paused"
    blocked = host.invoke("echo", "echo", {"message": "must not run"})
    assert blocked.status.value == "blocked"
    assert blocked.error is not None
    assert "paused" in blocked.error.message

    resumed = host.resume("echo")
    assert resumed.status == "connected"
    result = host.invoke("echo", "echo", {"message": "runs again"})
    assert result.status.value == "completed"


def test_plugin_process_failure_isolated_in_failed_envelope(host):
    host.connect("echo", approval=True)

    result = host.invoke("echo", "crash", {})

    assert result.status.value == "failed"
    assert result.error is not None
    assert "exited" in result.error.message


def test_unknown_permission_scope_cannot_connect(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    manifest = PluginManifest.model_validate({
        "id": "restricted", "version": "1.0.0", "name": "Restricted",
        "protocolVersion": "1", "command": [sys.executable, str(FIXTURES / "echo_plugin.py")],
        "permissions": [{"id": "external.send", "description": "Send", "sideEffectLevel": "external"}],
        "actions": [{"id": "send", "description": "Send", "permissionIds": ["external.send"], "sideEffectLevel": "external"}],
    })
    host = PluginHost(store, allowed_scope_ids={"local.read"})
    host.register(manifest)

    with pytest.raises(PermissionError):
        host.connect("restricted", approval=True)


def test_routing_capabilities_require_connected_healthy_plugin(host):
    manifest_data = host._manifest("echo", host.registrations.get("echo").manifest).model_dump(mode="json", by_alias=True)
    manifest_data["capabilities"] = [{
        "id": "echo-search",
        "displayName": "Echo Search",
        "intents": ["search"],
        "triggerPhrases": ["echo search"],
        "actionId": "echo",
        "permissionIds": ["local.read"],
        "sideEffectLevel": "none",
    }]
    manifest = PluginManifest.model_validate(manifest_data)
    host._manifests["echo"] = manifest
    host.registrations.set_status("echo", "available")

    assert host.routing_capabilities() == []

    host.connect("echo", approval=True)
    available = host.routing_capabilities()
    assert [item.id for item in available] == ["plugin:echo:echo-search"]

    host.pause("echo")
    assert host.routing_capabilities() == []
