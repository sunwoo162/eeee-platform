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


# These are deliberately routing descriptors, not a second provider API. The
# provider connector remains the source of truth for the operation itself.
_GENERIC_PLUGIN_ACTIONS: dict[str, tuple[dict[str, object], ...]] = {
    "gmail": (
        {"action": "mail.list", "name": "Gmail Mail", "intents": ["email", "mail"], "triggers": ["메일", "이메일", "gmail", "지메일"], "permission": "mail.read", "effect": SideEffectLevel.NONE},
        {"action": "mail.send", "name": "Gmail Send Mail", "intents": ["email", "mail"], "triggers": ["메일 보내", "이메일 보내", "gmail 보내"], "permission": "mail.send", "effect": SideEffectLevel.EXTERNAL},
    ),
    "google-calendar": (
        {"action": "calendar.events", "name": "Google Calendar Events", "intents": ["calendar", "schedule"], "triggers": ["구글 캘린더", "google calendar", "캘린더 일정"], "permission": "calendar.read", "effect": SideEffectLevel.NONE},
        {"action": "calendar.create", "name": "Google Calendar Create", "intents": ["calendar", "schedule"], "triggers": ["캘린더 일정 추가", "캘린더 일정 만들어"], "permission": "calendar.write", "effect": SideEffectLevel.EXTERNAL},
    ),
    "google-drive": (
        {"action": "files.list", "name": "Google Drive Files", "intents": ["files", "documents"], "triggers": ["구글 드라이브", "google drive", "드라이브 파일"], "permission": "files.read", "effect": SideEffectLevel.NONE},
        {"action": "files.create", "name": "Google Drive Create File", "intents": ["files", "documents"], "triggers": ["드라이브 파일 만들어", "구글 드라이브에 저장"], "permission": "files.write", "effect": SideEffectLevel.EXTERNAL},
    ),
    "google-contacts": (
        {"action": "contacts.list", "name": "Google Contacts", "intents": ["contacts"], "triggers": ["구글 연락처", "google contacts", "연락처"], "permission": "contacts.read", "effect": SideEffectLevel.NONE},
    ),
    "github": (
        {"action": "repos.list", "name": "GitHub Repositories", "intents": ["code", "repository"], "triggers": ["github 저장소", "깃허브 저장소", "github repo"], "permission": "repos.read", "effect": SideEffectLevel.NONE},
        {"action": "issues.list", "name": "GitHub Issues", "intents": ["code", "issues"], "triggers": ["github 이슈", "깃허브 이슈"], "permission": "issues.read", "effect": SideEffectLevel.NONE},
        {"action": "pull_requests.write", "name": "GitHub Pull Request", "intents": ["code", "review"], "triggers": ["github pr", "깃허브 pr", "풀 리퀘스트"], "permission": "pull_requests.write", "effect": SideEffectLevel.EXTERNAL},
    ),
    "figma": (
        {"action": "files.get", "name": "Figma Files", "intents": ["design", "files"], "triggers": ["figma", "피그마"], "permission": "files.read", "effect": SideEffectLevel.NONE},
        {"action": "files.write", "name": "Figma Edit File", "intents": ["design", "files"], "triggers": ["피그마 수정", "figma 수정"], "permission": "files.write", "effect": SideEffectLevel.EXTERNAL},
    ),
    "slack": (
        {"action": "messages.list", "name": "Slack Messages", "intents": ["chat", "messages"], "triggers": ["slack", "슬랙"], "permission": "messages.read", "effect": SideEffectLevel.NONE},
        {"action": "messages.send", "name": "Slack Send Message", "intents": ["chat", "messages"], "triggers": ["슬랙 메시지 보내", "slack 메시지 보내"], "permission": "messages.write", "effect": SideEffectLevel.EXTERNAL},
    ),
    "linear": (
        {"action": "issues.search", "name": "Linear Issues", "intents": ["issues", "project"], "triggers": ["linear", "리니어"], "permission": "issues.read", "effect": SideEffectLevel.NONE},
        {"action": "issues.create", "name": "Linear Create Issue", "intents": ["issues", "project"], "triggers": ["linear 이슈 만들어", "리니어 이슈 만들어"], "permission": "issues.write", "effect": SideEffectLevel.EXTERNAL},
    ),
    "todoist": (
        {"action": "tasks.list", "name": "Todoist Tasks", "intents": ["tasks", "todo"], "triggers": ["todoist", "투두이스트", "할 일 목록"], "permission": "tasks.read", "effect": SideEffectLevel.NONE},
        {"action": "tasks.create", "name": "Todoist Create Task", "intents": ["tasks", "todo"], "triggers": ["todoist 할 일 추가", "할 일 추가"], "permission": "tasks.write", "effect": SideEffectLevel.EXTERNAL},
    ),
    "outlook-email": (
        {"action": "mail.list", "name": "Outlook Mail", "intents": ["email", "mail"], "triggers": ["아웃룩 메일", "outlook mail"], "permission": "mail.read", "effect": SideEffectLevel.NONE},
        {"action": "mail.send", "name": "Outlook Send Mail", "intents": ["email", "mail"], "triggers": ["아웃룩 메일 보내", "outlook mail 보내"], "permission": "mail.send", "effect": SideEffectLevel.EXTERNAL},
    ),
    "outlook-calendar": (
        {"action": "calendar.events", "name": "Outlook Calendar", "intents": ["calendar", "schedule"], "triggers": ["아웃룩 캘린더", "outlook calendar"], "permission": "calendar.read", "effect": SideEffectLevel.NONE},
        {"action": "calendar.create", "name": "Outlook Create Event", "intents": ["calendar", "schedule"], "triggers": ["아웃룩 일정 추가", "outlook 일정 추가"], "permission": "calendar.write", "effect": SideEffectLevel.EXTERNAL},
    ),
}


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
        # Installation is a local catalog decision. Provider availability and
        # account connection are checked later at connect/OAuth time.
        installation = self.installations.install(entry.id, entry.version)
        return PluginInstallationView(
            pluginId=installation.plugin_id, version=installation.version, status="available"
        )

    def uninstall(self, plugin_id: str) -> None:
        self.catalog_source.get(plugin_id)
        for connection in self.connections.list_all():
            if connection.plugin_id != plugin_id:
                continue
            if connection.credential_ref:
                self.credentials.delete(connection.credential_ref)
            self.connections.remove(connection.user_id, plugin_id)
        self.installations.remove(plugin_id)

    def status(self, plugin_id: str, user_id: str = "local-user") -> str:
        """Return the actionable lifecycle state used by assistant routing.

        Installation is intentionally separate from authentication: a user can
        have a plugin available on the machine without having connected an
        account for it yet.
        """
        self.catalog_source.get(plugin_id)
        entry = self.catalog_source.get(plugin_id)
        if not self.installations.is_installed(plugin_id):
            return "not_installed"
        if entry.connector not in self.connectors:
            return "installed"
        try:
            return self.connections.get(user_id, plugin_id).status
        except KeyError:
            return "awaiting_authentication"

    def begin_oauth(
        self,
        user_id: str,
        plugin_id: str,
        approved_permissions: set[str],
        account_label: str | None,
    ) -> None:
        """Record an in-flight OAuth attempt without storing a provider secret."""
        entry = self.catalog_source.get(plugin_id)
        if not self.installations.is_installed(plugin_id):
            raise RuntimeError("plugin must be installed before connecting")
        if entry.connector not in self.connectors:
            raise RuntimeError(f"plugin connector is unavailable: {entry.connector}")
        if not approved_permissions or not approved_permissions.issubset(set(entry.permissions)):
            raise PermissionError("plugin permission approval is invalid")
        try:
            prior = self.connections.get(user_id, plugin_id)
        except KeyError:
            prior = None
        self.connections.save(PluginConnection(
            userId=user_id, pluginId=plugin_id, status="connecting",
            approvedPermissions=sorted(approved_permissions),
            credentialRef=prior.credential_ref if prior else None,
            accountLabel=account_label, updatedAt=_now(),
        ))

    def fail_oauth(self, user_id: str, plugin_id: str, error: str) -> None:
        try:
            connection = self.connections.get(user_id, plugin_id)
        except KeyError:
            return
        self.connections.save(connection.model_copy(update={
            "status": "failed", "last_health": "unavailable", "last_error": error,
            "updated_at": _now(),
        }))

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
        try:
            prior = self.connections.get(user_id, plugin_id)
        except KeyError:
            prior = None
        reference = self.credentials.put(user_id, plugin_id, _credential_json(credential))
        connecting = PluginConnection(
            userId=user_id, pluginId=plugin_id, status="connecting",
            approvedPermissions=sorted(approved_permissions), credentialRef=reference,
            accountLabel=account_label, updatedAt=_now(),
        )
        try:
            transient = connector.connect(user_id, credential, approved_permissions)
            health = connector.health(transient)
        except Exception:
            self.credentials.delete(reference)
            if prior is not None and prior.status in {"connected", "paused"}:
                return self._view(prior)
            failed = connecting.model_copy(update={
                "status": "failed", "credential_ref": None,
                "last_health": "unavailable", "last_error": "provider_unavailable",
                "updated_at": _now(),
            })
            self.connections.save(failed)
            return self._view(failed)
        if health.status != "healthy":
            self.credentials.delete(reference)
            if prior is not None and prior.status in {"connected", "paused"}:
                return self._view(prior)
            failed = connecting.model_copy(update={
                "status": "failed", "credential_ref": None,
                "last_health": health.status, "last_error": health.code,
                "updated_at": _now(),
            })
            self.connections.save(failed)
            return self._view(failed)
        connected = connecting.model_copy(update={
            "status": "connected", "last_health": "healthy", "last_error": None,
            "updated_at": _now(),
        })
        self.connections.save(connected)
        if prior is not None and prior.credential_ref and prior.credential_ref != reference:
            self.credentials.delete(prior.credential_ref)
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

    def pause(self, user_id: str, plugin_id: str) -> PluginConnectionView:
        connection = self.connections.get(user_id, plugin_id)
        paused = connection.model_copy(update={"status": "paused", "updated_at": _now()})
        self.connections.save(paused)
        return self._view(paused)

    def resume(self, user_id: str, plugin_id: str) -> PluginConnectionView:
        connection = self.connections.get(user_id, plugin_id)
        if not self.installations.is_installed(plugin_id):
            raise RuntimeError("plugin must be installed before resuming")
        health = self.health(user_id, plugin_id)
        refreshed = self.connections.get(user_id, plugin_id)
        return self._view(refreshed)

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
                continue
            for action in _GENERIC_PLUGIN_ACTIONS.get(entry.id, ()):
                if str(action["permission"]) not in connection.approved_permissions:
                    continue
                projected.append(CapabilityDescriptor(
                    id=f"plugin:{entry.id}:{action['action']}", version=entry.version,
                    display_name=str(action["name"]), intents=list(action["intents"]),
                    trigger_phrases=list(action["triggers"]),
                    required_connectors=[f"plugin:{entry.id}"],
                    side_effect_level=action["effect"], approval_level="user" if action["effect"] != SideEffectLevel.NONE else "none",
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
            action = str(value.get("action") or capability_id.rsplit(":", 1)[-1])
            if plugin_id == "notion" and action == "pages":
                action = "get_page"
            output = connector.invoke(transient, action, value)
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
