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
        "credentialFields": [
            {"key": "token", "label": "Notion token", "secret": True, "required": True, "placeholder": "secret_…"},
            {"key": "parentPageId", "label": "Parent page ID", "secret": False, "required": True, "placeholder": None},
        ],
        "permissionDetails": [
            {"id": "pages.read", "label": "페이지 읽기", "description": "Notion 페이지를 읽습니다.", "effect": "none", "defaultApproved": True, "requires": []},
            {"id": "pages.write", "label": "페이지 쓰기", "description": "Notion 페이지를 만들거나 수정합니다.", "effect": "external", "defaultApproved": False, "requires": ["pages.read"]},
        ],
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
        "eeee-chat-history",
        "gmail", "google-calendar", "google-drive", "google-contacts",
        "github", "figma", "slack", "linear", "todoist",
        "outlook-email", "outlook-calendar", "notion",
    }.issubset(ids)


def test_chat_history_catalog_entry_is_local_and_installable_without_account() -> None:
    entry = PluginCatalog().get("eeee-chat-history")

    assert entry.auth_mode == "none"
    assert entry.connector == "eeee-core"
    assert entry.permissions == ["conversation.read", "conversation.write"]
    assert entry.default_installed is False


def test_catalog_exposes_credential_fields_and_safe_permission_defaults() -> None:
    notion = PluginCatalog().get("notion")

    assert [field.key for field in notion.credential_fields] == ["token", "parentPageId"]
    assert notion.credential_fields[0].secret is True
    assert notion.credential_fields[1].secret is False
    assert notion.permission_details[0].default_approved is True
    assert notion.permission_details[1].default_approved is False
