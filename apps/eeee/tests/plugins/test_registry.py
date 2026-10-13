import pytest

from app.plugins.registry import PluginRegistry, PluginRegistryEntry


def _entry(**overrides):
    values = {
        "id": "gmail",
        "name": "Gmail",
        "version": "1.0.0",
        "description": "Gmail connector",
        "provider": "google",
        "protocol": "openapi-oauth",
        "authMode": "oauth-pkce",
        "permissions": ["mail.read"],
        "connectorId": "gmail",
        "availability": "available",
        "defaultInstalled": False,
        "capabilities": [],
    }
    values.update(overrides)
    return PluginRegistryEntry.model_validate(values)


def test_registry_accepts_only_entries_with_registered_connectors() -> None:
    registry = PluginRegistry([_entry()], connectors={"gmail": object()})

    assert registry.get("gmail").name == "Gmail"
    assert [entry.id for entry in registry.installable()] == ["gmail"]


def test_registry_rejects_unknown_connector_for_installable_entry() -> None:
    with pytest.raises(ValueError, match="unknown connector"):
        PluginRegistry([_entry()], connectors={})


def test_registry_does_not_make_coming_soon_entry_installable() -> None:
    registry = PluginRegistry(
        [_entry(availability="coming_soon", connectorId="future")], connectors={}
    )

    assert registry.installable() == []
    assert registry.get("gmail").availability == "coming_soon"


def test_registry_rejects_duplicate_plugin_ids() -> None:
    with pytest.raises(ValueError, match="duplicate plugin id"):
        PluginRegistry([_entry(), _entry()], connectors={"gmail": object()})


def test_registry_rejects_duplicate_permission_ids() -> None:
    with pytest.raises(ValueError, match="duplicate permission"):
        _entry(permissions=["mail.read", "mail.read"])
