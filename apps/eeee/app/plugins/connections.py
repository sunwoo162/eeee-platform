"""User-scoped plugin connection contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ConnectionStatus = Literal[
    "awaiting_authentication", "connecting", "connected", "paused", "failed",
]


class PluginConnection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    user_id: str = Field(min_length=1, alias="userId")
    plugin_id: str = Field(min_length=1, alias="pluginId")
    status: ConnectionStatus
    approved_permissions: list[str] = Field(default_factory=list, alias="approvedPermissions")
    credential_ref: str | None = Field(default=None, alias="credentialRef")
    account_label: str | None = Field(default=None, alias="accountLabel")
    last_health: Literal["healthy", "unhealthy", "unavailable"] | None = Field(default=None, alias="lastHealth")
    last_error: str | None = Field(default=None, alias="lastError")
    updated_at: str = Field(min_length=1, alias="updatedAt")
