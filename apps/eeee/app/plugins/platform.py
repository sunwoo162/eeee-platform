"""Installation, connection, and capability orchestration for optional plugins."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.assistant.models import CapabilityDescriptor
from app.contracts import ExecutionEnvelope, ExecutionError, ExecutionStatus, SideEffectLevel
from app.plugins.catalog import PluginCatalog, PluginCatalogEntry
from app.plugins.connections import PluginConnection
from app.plugins.connectors import ConnectorConnection, ConnectorHealth, PluginConnector
from app.plugins.credentials import KeyringCredentialStore
from app.runtime.store import PluginConnectionStore, PluginInstallation, PluginInstallationStore
from app.storage.sqlite import SQLiteStore


class PluginInstallationView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    plugin_id: str = Field(alias="pluginId")
    version: str
    status: str


class PluginConnectionView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    plugin_id: str = Field(alias="pluginId")
    status: str
    approved_permissions: list[str] = Field(alias="approvedPermissions")
    account_label: str | None = Field(default=None, alias="accountLabel")
    last_health: str | None = Field(default=None, alias="lastHealth")
    last_error: str | None = Field(default=None, alias="lastError")
    updated_at: str = Field(alias="updatedAt")


class PluginPlatformService:
    def __init__(
        self,
        store: SQLiteStore,
        *,
        catalog: PluginCatalog | None = None,
        credentials=None,
        connectors: Mapping[str, PluginConnector] | None = None,
    ) -> None:
        self.catalog_source = catalog or PluginCatalog()
        self.installations = PluginInstallationStore(store)
        self.connections = PluginConnectionStore(store)
        self.credentials = credentials or KeyringCredentialStore()
        self.connectors = dict(connectors or {})

    def catalog(self) -> list[PluginCatalogEntry]:
        return self.catalog_source.list()

    def install(self, plugin_id: str) -> PluginInstallationView:
        entry = self.catalog_source.get(plugin_id)
        installation = self.installations.install(entry.id, entry.version)
        return PluginInstallationView(
            pluginId=installation.plugin_id, version=installation.version, status="available"
        )

    def uninstall(self, plugin_id: str) -> None:
        self.catalog_source.get(plugin_id)
        self.installations.remove(plugin_id)

    def status(self, plugin_id: str, user_id: str = "local-user") -> str:
        """Return the actionable lifecycle state used by assistant routing.

        Installation is intentionally separate from authentication: a user can
        have a plugin available on the machine without having connected an
        account for it yet.
        """
        self.catalog_source.get(plugin_id)
        if not self.installations.is_installed(plugin_id):
            return "not_installed"
        try:
            return self.connections.get(user_id, plugin_id).status
        except KeyError:
            return "awaiting_authentication"

    def connect(
        self,
        user_id: str,
        plugin_id: str,
        approved_permissions: set[str],
        credential: Mapping[str, str],
        account_label: str | None,
    ) -> PluginConnectionView:
        entry = self.catalog_source.get(plugin_id)
        if not self.installations.is_installed(plugin_id):
            raise RuntimeError("plugin must be installed before connecting")
        requested = set(entry.permissions)
        if not approved_permissions or not approved_permissions.issubset(requested):
            raise PermissionError("plugin permission approval is invalid")
        connector = self._connector(plugin_id)
        reference = self.credentials.put(user_id, plugin_id, _credential_json(credential))
        connecting = PluginConnection(
            userId=user_id, pluginId=plugin_id, status="connecting",
            approvedPermissions=sorted(approved_permissions), credentialRef=reference,
            accountLabel=account_label, updatedAt=_now(),
        )
        self.connections.save(connecting)
        try:
            transient = connector.connect(user_id, credential, approved_permissions)
            health = connector.health(transient)
        except Exception:
            failed = connecting.model_copy(update={
                "status": "failed", "last_health": "unavailable", "last_error": "provider_unavailable",
                "updated_at": _now(),
            })
            self.connections.save(failed)
            return self._view(failed)
        if health.status != "healthy":
            failed = connecting.model_copy(update={
                "status": "failed", "last_health": health.status, "last_error": health.code,
                "updated_at": _now(),
            })
            self.connections.save(failed)
            return self._view(failed)
        connected = connecting.model_copy(update={
            "status": "connected", "last_health": "healthy", "last_error": None,
            "updated_at": _now(),
        })
        self.connections.save(connected)
        return self._view(connected)

    def get_connection(self, user_id: str, plugin_id: str) -> PluginConnectionView:
        return self._view(self.connections.get(user_id, plugin_id))

    def disconnect(self, user_id: str, plugin_id: str) -> None:
        connection = self.connections.get(user_id, plugin_id)
        connector = self._connector(plugin_id)
        credential = self.credentials.get(connection.credential_ref) if connection.credential_ref else None
        if credential is not None:
            connector.disconnect(connector.connect(user_id, _credential_from_json(credential), set(connection.approved_permissions)))
        if connection.credential_ref:
            self.credentials.delete(connection.credential_ref)
        self.connections.remove(user_id, plugin_id)

    def health(self, user_id: str, plugin_id: str) -> ConnectorHealth:
        connection = self.connections.get(user_id, plugin_id)
        connector = self._connector(plugin_id)
        credential = self.credentials.get(connection.credential_ref) if connection.credential_ref else None
        if credential is None:
            health = ConnectorHealth(status="unavailable", code="reauthentication_required", reason="Plugin credential is unavailable")
        else:
            transient = connector.connect(user_id, _credential_from_json(credential), set(connection.approved_permissions))
            health = connector.health(transient)
        status = "connected" if health.status == "healthy" else "failed"
        self.connections.save(connection.model_copy(update={
            "status": status, "last_health": health.status, "last_error": None if status == "connected" else health.code,
            "updated_at": _now(),
        }))
        return health

    def capabilities(self, user_id: str = "local-user") -> list[CapabilityDescriptor]:
        projected: list[CapabilityDescriptor] = []
        for entry in self.catalog_source.list():
            if not self.installations.is_installed(entry.id):
                continue
            try:
                connection = self.connections.get(user_id, entry.id)
            except KeyError:
                continue
            if connection.status != "connected":
                continue
            health = self.health(user_id, entry.id)
            if health.status != "healthy":
                continue
            if entry.id == "notion":
                projected.append(CapabilityDescriptor(
                    id="plugin:notion:pages", version=entry.version,
                    display_name="Notion Pages", intents=["documents", "notes", "knowledge"],
                    trigger_phrases=["노션", "notion"], required_connectors=["plugin:notion"],
                    side_effect_level=SideEffectLevel.EXTERNAL, approval_level="user",
                    claim_latch_policy="claimlatch-v0.2.0", memory_writable=False,
                ))
        return projected

    def invoke(self, user_id: str, capability_id: str, value: dict[str, object]) -> ExecutionEnvelope:
        if capability_id not in {item.id for item in self.capabilities(user_id)}:
            return _blocked_envelope(capability_id, "plugin capability is not connected and healthy")
        plugin_id = capability_id.split(":", 2)[1]
        connection = self.connections.get(user_id, plugin_id)
        credential = self.credentials.get(connection.credential_ref) if connection.credential_ref else None
        if credential is None:
            return _blocked_envelope(capability_id, "plugin credential is unavailable")
        try:
            connector = self._connector(plugin_id)
            transient = connector.connect(user_id, _credential_from_json(credential), set(connection.approved_permissions))
            output = connector.invoke(transient, str(value.get("action", "get_page")), value)
            envelope = ExecutionEnvelope(
                executionId=f"plugin-execution-{uuid4().hex}", requestId=f"plugin-request-{uuid4().hex}",
                capabilityId=capability_id, toolId=plugin_id, actor="EEEE", input=value,
            )
            running = envelope.transition(ExecutionStatus.RUNNING)
            return running.transition(ExecutionStatus.COMPLETED, output=output)
        except Exception as exc:
            return _blocked_envelope(capability_id, str(exc).strip() or "plugin invocation failed")

    def _connector(self, plugin_id: str) -> PluginConnector:
        try:
            return self.connectors[plugin_id]
        except KeyError as exc:
            raise RuntimeError(f"plugin connector is unavailable: {plugin_id}") from exc

    @staticmethod
    def _view(connection: PluginConnection) -> PluginConnectionView:
        return PluginConnectionView(
            pluginId=connection.plugin_id, status=connection.status,
            approvedPermissions=connection.approved_permissions,
            accountLabel=connection.account_label, lastHealth=connection.last_health,
            lastError=connection.last_error, updatedAt=connection.updated_at,
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _credential_json(value: Mapping[str, str]) -> str:
    import json

    if not value or any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise ValueError("credential must be a nonempty string mapping")
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True)


def _credential_from_json(value: str) -> dict[str, str]:
    import json

    payload = json.loads(value)
    if not isinstance(payload, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in payload.items()):
        raise ValueError("stored credential is invalid")
    return payload


def _blocked_envelope(capability_id: str, message: str) -> ExecutionEnvelope:
    envelope = ExecutionEnvelope(
        executionId=f"plugin-execution-{uuid4().hex}", requestId=f"plugin-request-{uuid4().hex}",
        capabilityId=capability_id, toolId="plugin", actor="EEEE", input={},
    )
    return envelope.transition(
        ExecutionStatus.BLOCKED,
        output={"status": "blocked", "message": message},
        error=ExecutionError(code="plugin_blocked", message=message),
    )
