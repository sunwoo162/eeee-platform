import pytest

from app.plugins.manifest import PluginManifest, discover_manifest


def _manifest(**updates):
    value = {
        "id": "echo",
        "version": "1.0.0",
        "name": "Echo Plugin",
        "protocolVersion": "1",
        "command": ["python", "echo_plugin.py"],
        "permissions": [{
            "id": "local.read", "description": "Read local input", "sideEffectLevel": "none",
        }],
        "actions": [{
            "id": "echo", "description": "Echo input", "permissionIds": ["local.read"],
            "sideEffectLevel": "none",
        }],
    }
    value.update(updates)
    return value


def test_valid_manifest_is_strict_and_exposes_permissions():
    manifest = PluginManifest.model_validate(_manifest())

    assert manifest.id == "echo"
    assert manifest.actions[0].permission_ids == ["local.read"]
    assert manifest.permissions[0].side_effect_level.value == "none"
    assert manifest.capabilities == []


def test_manifest_exposes_optional_routing_capabilities():
    manifest = PluginManifest.model_validate(_manifest(capabilities=[{
        "id": "echo-search",
        "displayName": "Echo Search",
        "intents": ["search"],
        "triggerPhrases": ["echo search"],
        "actionId": "echo",
        "permissionIds": ["local.read"],
        "sideEffectLevel": "none",
    }]))

    capability = manifest.capabilities[0]
    assert capability.id == "echo-search"
    assert capability.action_id == "echo"
    assert capability.trigger_phrases == ["echo search"]


def test_manifest_rejects_unknown_protocol_and_side_effect():
    with pytest.raises(ValueError, match="protocol"):
        PluginManifest.model_validate(_manifest(protocolVersion="9"))
    with pytest.raises(ValueError):
        PluginManifest.model_validate(_manifest(permissions=[{
            "id": "x", "description": "x", "sideEffectLevel": "remote-unknown",
        }]))


def test_discover_rejects_malformed_manifest(tmp_path):
    path = tmp_path / "plugin.json"
    path.write_text("{\"id\": \"broken\"}", encoding="utf-8")

    with pytest.raises(ValueError):
        discover_manifest(path)
