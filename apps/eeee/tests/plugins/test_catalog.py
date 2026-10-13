import pytest

from app.plugins.catalog import PluginCatalog, PluginCatalogEntry


def test_bundled_catalog_exposes_notion_as_optional_not_installed() -> None:
    entry = PluginCatalog().get("notion")

    assert entry.model_dump(by_alias=True) == {
        "id": "notion",
        "name": "Notion",
        "version": "1.0.0",
        "description": "Notion pages connector",
        "authMode": "token-or-oauth",
        "permissions": ["pages.read", "pages.write"],
        "installSource": "bundled-optional",
        "defaultInstalled": False,
        "connector": "notion",
    }


def test_catalog_rejects_blank_or_duplicate_permission_ids() -> None:
    with pytest.raises(ValueError):
        PluginCatalogEntry(
            id="sample", name="Sample", version="1.0.0", description="sample",
            auth_mode="token", permissions=[""], install_source="bundled-optional",
            default_installed=False, connector="sample",
        )

    with pytest.raises(ValueError):
        PluginCatalogEntry(
            id="sample", name="Sample", version="1.0.0", description="sample",
            auth_mode="token", permissions=["pages.read", "pages.read"],
            install_source="bundled-optional", default_installed=False, connector="sample",
        )


def test_unknown_catalog_plugin_is_not_silently_created() -> None:
    with pytest.raises(KeyError):
        PluginCatalog().get("unknown")


def test_catalog_includes_first_party_connector_candidates() -> None:
    ids = {entry.id for entry in PluginCatalog().list()}

    assert {
        "gmail", "google-calendar", "google-drive", "google-contacts",
        "github", "figma", "slack", "linear", "todoist",
        "outlook-email", "outlook-calendar", "notion",
    }.issubset(ids)
