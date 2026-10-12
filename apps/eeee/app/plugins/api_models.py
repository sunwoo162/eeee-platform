"""Redacted DTOs for the local plugin control center."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class PluginConnectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    approved_permissions: list[str] = Field(alias="approvedPermissions", min_length=1)
    credential: dict[str, SecretStr] = Field(min_length=1)
    account_label: str | None = Field(default=None, alias="accountLabel", max_length=160)

    def plain_credential(self) -> dict[str, str]:
        return {key: value.get_secret_value() for key, value in self.credential.items()}


class PluginCatalogView(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    name: str
    version: str
    description: str
    auth_mode: str = Field(alias="authMode")
    permissions: list[str]
    install_source: str = Field(alias="installSource")
    default_installed: bool = Field(alias="defaultInstalled")
    status: str
    next_action: str = Field(alias="nextAction")


class PluginHealthView(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    plugin_id: str = Field(alias="pluginId")
    status: str
    code: str
    reason: str
