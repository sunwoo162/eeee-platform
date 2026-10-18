import pytest

from app.plugins.models import PluginManifest


def test_plugin_manifest_validates_auth_health_and_memory_scope():
    manifest = PluginManifest.model_validate(
        {
            "id": "calendar",
            "version": "1.0.0",
            "name": "Calendar",
            "protocolVersion": "1",
            "command": ["python", "calendar.py"],
            "auth": {"mode": "oauth", "provider": "google"},
            "health": {"action": "__health__", "timeoutMs": 2000},
            "memoryScope": "account",
            "permissions": [
                {"id": "calendar.read", "description": "Read events", "sideEffectLevel": "none"}
            ],
            "actions": [
                {
                    "id": "list",
                    "description": "List events",
                    "permissionIds": ["calendar.read"],
                    "sideEffectLevel": "none",
                    "inputSchema": {"type": "object"},
                }
            ],
        }
    )

    assert manifest.auth.mode == "oauth"
    assert manifest.health.timeout_ms == 2000
    assert manifest.memory_scope == "account"


def test_plugin_manifest_rejects_invalid_auth_and_memory_scope():
    base = {
        "id": "broken",
        "version": "1.0.0",
        "name": "Broken",
        "protocolVersion": "1",
        "command": ["python", "broken.py"],
    }
    with pytest.raises(ValueError):
        PluginManifest.model_validate({**base, "auth": {"mode": "magic"}})
    with pytest.raises(ValueError):
        PluginManifest.model_validate({**base, "memoryScope": "global"})
