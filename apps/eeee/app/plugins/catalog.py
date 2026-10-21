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
    default_approved: bool | None = Field(default=None, alias="defaultApproved")
    requires: list[str] = Field(default_factory=list)

    @field_validator("requires")
    @classmethod
    def validate_requires(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("permission requirements must not be blank")
        if len(set(values)) != len(values):
            raise ValueError("permission requirements must not be duplicated")
        return values


class PluginCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    auth_mode: Literal["none", "token", "oauth", "token-or-oauth"] = Field(alias="authMode")
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
    """Read-only bundled catalog for optional connectors and first-party UI plugins."""

    _entries = (
        PluginCatalogEntry(
            id="eeee-chat-history", name="EEEE 채팅 기록", version="1.0.0",
            description="EEEE에게 보낸 명령과 답변을 휴대폰 채팅처럼 확인하고 이어서 대화하는 플러그인",
            authMode="none", permissions=["conversation.read", "conversation.write"],
            permissionDetails=[
                PermissionDetail(
                    id="conversation.read", label="대화 기록 읽기",
                    description="EEEE 대화 기록을 읽습니다.", defaultApproved=True,
                ),
                PermissionDetail(
                    id="conversation.write", label="대화 보내기",
                    description="같은 대화에 새 명령을 보냅니다.", defaultApproved=True,
                ),
            ],
            installSource="bundled-optional", defaultInstalled=False,
            connector="eeee-core",
        ),
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
                    defaultApproved=False, requires=["pages.read"],
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


def permission_closure(entry: PluginCatalogEntry, selected: set[str]) -> set[str]:
    """Return the selected permissions plus all declared transitive requirements."""

    available = set(entry.permissions)
    if not selected or not selected.issubset(available):
        raise PermissionError("plugin permission approval is invalid")
    details = {detail.id: detail for detail in entry.permission_details}
    closure = set(selected)
    pending = list(selected)
    while pending:
        permission = pending.pop()
        detail = details.get(permission)
        for required in detail.requires if detail else []:
            if required not in available:
                raise PermissionError(
                    f"permission {permission} requires unknown permission {required}"
                )
            if required not in closure:
                closure.add(required)
                pending.append(required)
    return closure


def validate_permission_selection(entry: PluginCatalogEntry, selected: set[str]) -> set[str]:
    """Reject a selection that omits any dependency instead of silently widening it."""

    closure = permission_closure(entry, selected)
    if closure != selected:
        missing = sorted(closure - selected)
        raise PermissionError(
            "plugin permission approval is missing required permissions: "
            + ", ".join(missing)
        )
    return closure
