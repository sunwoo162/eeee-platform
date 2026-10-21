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


def test_external_plugin_action_requires_explicit_invocation_approval(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    manifest = PluginManifest.model_validate({
        "id": "sender", "version": "1.0.0", "name": "Sender",
        "protocolVersion": "1", "command": [sys.executable, str(FIXTURES / "echo_plugin.py")],
        "permissions": [{"id": "external.send", "description": "Send externally", "sideEffectLevel": "external"}],
        "actions": [{"id": "send", "description": "Send externally", "permissionIds": ["external.send"], "sideEffectLevel": "external"}],
    })
    host = PluginHost(store, allowed_scope_ids={"external.send"})
    host.register(manifest)
    host.connect("sender", approval=True)

    awaiting = host.invoke("sender", "send", {"message": "hello"})
    assert awaiting.status.value == "awaiting_approval"
    assert awaiting.approval_state.value == "awaiting_approval"
    assert awaiting.required_approval is True
    assert awaiting.side_effect_level.value == "external"

    with pytest.raises(ValueError, match="execution_id"):
        host.invoke("sender", "send", {"message": "hello"}, approved=True)

    with pytest.raises(ValueError, match="does not match"):
        host.invoke("sender", "send", {"message": "changed"}, approved=True, execution_id=awaiting.execution_id)

    completed = host.invoke(
        "sender", "send", {"message": "hello"}, approved=True, execution_id=awaiting.execution_id
    )
    assert completed.status.value == "completed"
    assert completed.approval_state.value == "approved"

    duplicate = host.invoke(
        "sender", "send", {"message": "hello"}, approved=True, execution_id=awaiting.execution_id
    )
    assert duplicate.status.value == "completed"
    assert duplicate.execution_id == completed.execution_id


def test_manifest_rejects_action_with_weaker_side_effect_than_permission():
    with pytest.raises(ValueError, match="weaker side effect"):
        PluginManifest.model_validate({
            "id": "unsafe", "version": "1.0.0", "name": "Unsafe",
            "protocolVersion": "1", "command": ["python", "plugin.py"],
            "permissions": [{"id": "external.send", "description": "Send", "sideEffectLevel": "external"}],
            "actions": [{"id": "send", "description": "Send", "permissionIds": ["external.send"], "sideEffectLevel": "none"}],
        })
