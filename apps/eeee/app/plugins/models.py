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


class PluginCapability(BaseModel):
    """Routing metadata exported by an optional plugin, not its implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1, alias="displayName")
    intents: list[str] = Field(min_length=1)
    trigger_phrases: list[str] = Field(min_length=1, alias="triggerPhrases")
    action_id: str = Field(min_length=1, alias="actionId")
    permission_ids: list[str] = Field(default_factory=list, alias="permissionIds")
    side_effect_level: SideEffectLevel = Field(alias="sideEffectLevel")
    approval_level: Literal["none", "user", "always"] = Field(default="user", alias="approvalLevel")
    version: str = Field(default="1.0.0", min_length=1)
class PluginAuth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    mode: Literal["none", "oauth", "api_key", "local"] = "none"
    provider: str | None = None


class PluginHealthSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    action: str = "__health__"
    timeout_ms: int = Field(default=10_000, alias="timeoutMs", ge=100, le=120_000)


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    protocol_version: Literal["1"] = Field(alias="protocolVersion")
    command: list[str] = Field(min_length=1)
    permissions: list[PluginPermission] = Field(default_factory=list)
    actions: list[PluginAction] = Field(default_factory=list)
    capabilities: list[PluginCapability] = Field(default_factory=list)
    auth: PluginAuth = Field(default_factory=PluginAuth)
    health: PluginHealthSpec = Field(default_factory=PluginHealthSpec)
    memory_scope: Literal["none", "conversation", "project", "account"] = Field(
        default="none", alias="memoryScope"
    )

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
        capability_ids = [capability.id for capability in self.capabilities]
        if len(set(capability_ids)) != len(capability_ids):
            raise ValueError("plugin manifest contains duplicate capability IDs")
        action_ids_set = set(action_ids)
        for capability in self.capabilities:
            if capability.action_id not in action_ids_set:
                raise ValueError(f"plugin capability references unknown action: {capability.action_id}")
            missing_capability_permissions = set(capability.permission_ids) - set(permission_ids)
            if missing_capability_permissions:
                raise ValueError(
                    "plugin capability references unknown permissions: "
                    f"{sorted(missing_capability_permissions)}"
                )
        return self


PluginStatus = Literal[
    "available",
    "not_installed",
    "installed",
    "awaiting_authentication",
    "auth_required",
    "connected",
    "ready",
    "running",
    "degraded",
    "failed",
    "disabled",
    "removed",
    "connecting",
    "paused",
]
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
