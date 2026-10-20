"""Redacted DTOs for the local plugin control center."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.plugins.catalog import CredentialField, PermissionDetail


class PluginConnectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    approved_permissions: list[str] = Field(alias="approvedPermissions", min_length=1)
    credential: dict[str, SecretStr] = Field(min_length=1)
    account_label: str | None = Field(default=None, alias="accountLabel", max_length=160)

    def plain_credential(self) -> dict[str, str]:
        return {key: value.get_secret_value() for key, value in self.credential.items()}


class PluginOAuthStartPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    approved_permissions: list[str] = Field(alias="approvedPermissions", min_length=1)
    account_label: str | None = Field(default=None, alias="accountLabel", max_length=160)


class PluginCatalogView(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    name: str
    version: str
    description: str
    auth_mode: str = Field(alias="authMode")
    permissions: list[str]
    credential_fields: list[CredentialField] = Field(default_factory=list, alias="credentialFields")
    permission_details: list[PermissionDetail] = Field(default_factory=list, alias="permissionDetails")
    install_source: str = Field(alias="installSource")
    default_installed: bool = Field(alias="defaultInstalled")
    status: str
    setup_status: Literal[
        "ready", "provider_configuration_required", "connector_unavailable", "not_required"
    ] = Field(alias="setupStatus")
    setup_message: str = Field(alias="setupMessage")
    next_action: str = Field(alias="nextAction")


class PluginHealthView(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    plugin_id: str = Field(alias="pluginId")
    status: str
    code: str
    reason: str
