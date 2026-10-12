"""Bundled metadata for optional plugins; no remote registry or auto-install."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PluginCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    auth_mode: Literal["token", "oauth", "token-or-oauth"] = Field(alias="authMode")
    permissions: list[str] = Field(min_length=1)
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
            installSource="bundled-optional", defaultInstalled=False, connector="notion",
        ),
    )

    def list(self) -> list[PluginCatalogEntry]:
        return list(self._entries)

    def get(self, plugin_id: str) -> PluginCatalogEntry:
        for entry in self._entries:
            if entry.id == plugin_id:
                return entry
        raise KeyError(f"Plugin catalog entry not found: {plugin_id}")
