"""Bundled metadata for optional plugins; no remote registry or auto-install."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CredentialField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    secret: bool = False
    required: bool = True
    placeholder: str | None = None


class PermissionDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    effect: Literal["none", "external"] = "none"
    default_approved: bool = Field(default=False, alias="defaultApproved")


class PluginCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    auth_mode: Literal["token", "oauth", "token-or-oauth"] = Field(alias="authMode")
    permissions: list[str] = Field(min_length=1)
    credential_fields: list[CredentialField] = Field(default_factory=list, alias="credentialFields")
    permission_details: list[PermissionDetail] = Field(default_factory=list, alias="permissionDetails")
    install_source: Literal["bundled-optional"] = Field(alias="installSource")
    default_installed: bool = Field(alias="defaultInstalled")
    connector: str = Field(min_length=1)

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("plugin permissions must not be blank")
        if len(set(values)) != len(values):
            raise ValueError("plugin permissions must not be duplicated")
        return values


class PluginCatalog:
    """Read-only bundled catalog for currently supported optional connectors."""

    _entries = (
        PluginCatalogEntry(
            id="notion", name="Notion", version="1.0.0",
            description="Notion pages connector", authMode="token-or-oauth",
            permissions=["pages.read", "pages.write"],
            credentialFields=[
                CredentialField(key="token", label="Notion token", secret=True, placeholder="secret_…"),
                CredentialField(key="parentPageId", label="Parent page ID", secret=False),
            ],
            permissionDetails=[
                PermissionDetail(
                    id="pages.read", label="페이지 읽기",
                    description="Notion 페이지를 읽습니다.", defaultApproved=True,
                ),
                PermissionDetail(
                    id="pages.write", label="페이지 쓰기",
                    description="Notion 페이지를 만들거나 수정합니다.", effect="external",
                ),
            ],
            installSource="bundled-optional", defaultInstalled=False, connector="notion",
        ),
        PluginCatalogEntry(
            id="gmail", name="Gmail", version="1.0.0",
            description="Gmail messages connector", authMode="oauth",
            permissions=["mail.read", "mail.send"], installSource="bundled-optional",
            defaultInstalled=False, connector="gmail",
        ),
        PluginCatalogEntry(
            id="google-calendar", name="Google Calendar", version="1.0.0",
            description="Google Calendar connector", authMode="oauth",
            permissions=["calendar.read", "calendar.write"], installSource="bundled-optional",
            defaultInstalled=False, connector="google-calendar",
        ),
        PluginCatalogEntry(
            id="google-drive", name="Google Drive", version="1.0.0",
            description="Google Drive connector", authMode="oauth",
            permissions=["files.read", "files.write"], installSource="bundled-optional",
            defaultInstalled=False, connector="google-drive",
        ),
        PluginCatalogEntry(
            id="google-contacts", name="Google Contacts", version="1.0.0",
            description="Google Contacts connector", authMode="oauth",
            permissions=["contacts.read"], installSource="bundled-optional",
            defaultInstalled=False, connector="google-contacts",
        ),
        PluginCatalogEntry(
            id="github", name="GitHub", version="1.0.0",
            description="GitHub repositories and issues connector", authMode="oauth",
            permissions=["repos.read", "issues.read", "pull_requests.write"],
            installSource="bundled-optional", defaultInstalled=False, connector="github",
        ),
        PluginCatalogEntry(
            id="figma", name="Figma", version="1.0.0",
            description="Figma files and design connector", authMode="oauth",
            permissions=["files.read", "files.write"], installSource="bundled-optional",
            defaultInstalled=False, connector="figma",
        ),
        PluginCatalogEntry(
            id="slack", name="Slack", version="1.0.0",
            description="Slack messages and channels connector", authMode="oauth",
            permissions=["messages.read", "messages.write"], installSource="bundled-optional",
            defaultInstalled=False, connector="slack",
        ),
        PluginCatalogEntry(
            id="linear", name="Linear", version="1.0.0",
            description="Linear issues and projects connector", authMode="oauth",
            permissions=["issues.read", "issues.write"], installSource="bundled-optional",
            defaultInstalled=False, connector="linear",
        ),
        PluginCatalogEntry(
            id="todoist", name="Todoist", version="1.0.0",
            description="Todoist tasks connector", authMode="oauth",
            permissions=["tasks.read", "tasks.write"], installSource="bundled-optional",
            defaultInstalled=False, connector="todoist",
        ),
        PluginCatalogEntry(
            id="outlook-email", name="Outlook Email", version="1.0.0",
            description="Outlook Email connector", authMode="oauth",
            permissions=["mail.read", "mail.send"], installSource="bundled-optional",
            defaultInstalled=False, connector="outlook-email",
        ),
        PluginCatalogEntry(
            id="outlook-calendar", name="Outlook Calendar", version="1.0.0",
            description="Outlook Calendar connector", authMode="oauth",
            permissions=["calendar.read", "calendar.write"], installSource="bundled-optional",
            defaultInstalled=False, connector="outlook-calendar",
        ),
    )

    def list(self) -> list[PluginCatalogEntry]:
        return list(self._entries)

    def get(self, plugin_id: str) -> PluginCatalogEntry:
        for entry in self._entries:
            if entry.id == plugin_id:
                return entry
        raise KeyError(f"Plugin catalog entry not found: {plugin_id}")
