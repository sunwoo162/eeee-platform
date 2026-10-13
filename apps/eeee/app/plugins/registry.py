"""Validated metadata registry for installable external connectors."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PluginProtocol = Literal["mcp", "openapi-oauth", "local-process"]
PluginAuthMode = Literal["oauth-pkce", "token", "token-or-oauth", "none"]
PluginAvailability = Literal["available", "coming_soon", "disabled"]


class PluginRegistryEntry(BaseModel):
    """Provider-neutral install metadata.

    This model deliberately contains no executable command or secret. The
    connector registry supplies the implementation separately.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    protocol: PluginProtocol
    auth_mode: PluginAuthMode = Field(alias="authMode")
    permissions: list[str] = Field(min_length=1)
    connector_id: str = Field(alias="connectorId", min_length=1)
    availability: PluginAvailability = "available"
    default_installed: bool = Field(alias="defaultInstalled", default=False)
    capabilities: list[dict[str, object]] = Field(default_factory=list)

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("plugin permissions must not be blank")
        if len(set(values)) != len(values):
            raise ValueError("duplicate permission ids are not allowed")
        return values


class PluginRegistry:
    """Catalog that exposes only metadata backed by a known connector."""

    def __init__(
        self,
        entries: Iterable[PluginRegistryEntry],
        *,
        connectors: Mapping[str, object],
    ) -> None:
        self._entries = tuple(entries)
        self._connectors = connectors
        ids = [entry.id for entry in self._entries]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate plugin id")
        for entry in self._entries:
            if entry.availability == "available" and entry.connector_id not in connectors:
                raise ValueError(f"unknown connector: {entry.connector_id}")

    def list(self) -> list[PluginRegistryEntry]:
        return list(self._entries)

    def installable(self) -> list[PluginRegistryEntry]:
        return [
            entry for entry in self._entries
            if entry.availability == "available" and entry.connector_id in self._connectors
        ]

    def get(self, plugin_id: str) -> PluginRegistryEntry:
        for entry in self._entries:
            if entry.id == plugin_id:
                return entry
        raise KeyError(f"Plugin registry entry not found: {plugin_id}")
