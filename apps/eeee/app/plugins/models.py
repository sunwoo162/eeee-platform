"""Strict contracts for separately installed local plugins."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts import ExecutionEnvelope, SideEffectLevel


class PluginPermission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    side_effect_level: SideEffectLevel = Field(alias="sideEffectLevel")


class PluginAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    permission_ids: list[str] = Field(default_factory=list, alias="permissionIds")
    side_effect_level: SideEffectLevel = Field(alias="sideEffectLevel")
    input_schema: dict[str, object] = Field(default_factory=dict, alias="inputSchema")


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    protocol_version: Literal["1"] = Field(alias="protocolVersion")
    command: list[str] = Field(min_length=1)
    permissions: list[PluginPermission] = Field(default_factory=list)
    actions: list[PluginAction] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "PluginManifest":
        permission_ids = [permission.id for permission in self.permissions]
        if len(set(permission_ids)) != len(permission_ids):
            raise ValueError("plugin manifest contains duplicate permission IDs")
        action_ids = [action.id for action in self.actions]
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("plugin manifest contains duplicate action IDs")
        missing = {
            permission_id
            for action in self.actions
            for permission_id in action.permission_ids
            if permission_id not in permission_ids
        }
        if missing:
            raise ValueError(f"plugin action references unknown permissions: {sorted(missing)}")
        effect_rank = {
            SideEffectLevel.NONE: 0,
            SideEffectLevel.LOCAL: 1,
            SideEffectLevel.EXTERNAL: 2,
        }
        permissions_by_id = {permission.id: permission for permission in self.permissions}
        for action in self.actions:
            required_effect = max(
                (effect_rank[permissions_by_id[item].side_effect_level] for item in action.permission_ids),
                default=0,
            )
            if effect_rank[action.side_effect_level] < required_effect:
                raise ValueError(
                    f"plugin action {action.id!r} declares a weaker side effect than its permissions"
                )
        return self


PluginStatus = Literal["available", "connected", "paused", "failed", "disabled"]
PluginHealthStatus = Literal["healthy", "unhealthy", "unavailable"]


class PluginHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plugin_id: str
    status: PluginHealthStatus
    reason: str


class PluginInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    envelope: ExecutionEnvelope
    output: dict[str, object] | None = None
