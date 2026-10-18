"""Installation, connection, and capability orchestration for optional plugins."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from collections.abc import Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.assistant.models import CapabilityDescriptor
from app.contracts import ApprovalState, ExecutionEnvelope, ExecutionError, ExecutionStatus, SideEffectLevel
from app.plugins.catalog import PluginCatalog, PluginCatalogEntry
from app.plugins.connections import PluginConnection
from app.plugins.connectors import ConnectorConnection, ConnectorHealth, PluginConnector
from app.plugins.credentials import KeyringCredentialStore
from app.plugins.intents import build_plugin_action_input
from app.runtime.store import ExecutionStore, PluginConnectionStore, PluginInstallation, PluginInstallationStore
from app.storage.sqlite import SQLiteStore


logger = logging.getLogger(__name__)


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

_FIRST_PARTY_UI_PLUGIN_IDS = {"eeee-chat-history"}


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
        plugin_install_root: str | Path | None = None,
    ) -> None:
        self.catalog_source = catalog or PluginCatalog()
        self.installations = PluginInstallationStore(store)
        self.connections = PluginConnectionStore(store)
        self.executions = ExecutionStore(store)
        self.credentials = credentials or KeyringCredentialStore()
        self.connectors = dict(connectors or {})
        self.plugin_install_root = Path(plugin_install_root) if plugin_install_root else None
        self._bundled_plugin_root = Path(__file__).resolve().parents[2] / "plugins"

    def catalog(self) -> list[PluginCatalogEntry]:
        return self.catalog_source.list()

    def install(self, plugin_id: str) -> PluginInstallationView:
        entry = self.catalog_source.get(plugin_id)
        # Installation is a local catalog decision. Provider availability and
        # account connection are checked later at connect/OAuth time.
        if entry.id in _FIRST_PARTY_UI_PLUGIN_IDS:
            source = self._bundled_plugin_root / "eeee_chat_history"
            if not source.is_dir():
                raise RuntimeError(f"bundled plugin package is missing: {entry.id}")
            if self.plugin_install_root is not None:
                self.plugin_install_root.mkdir(parents=True, exist_ok=True)
                shutil.copytree(
                    source,
                    self.plugin_install_root / "eeee_chat_history",
                    dirs_exist_ok=True,
                )
        installation = self.installations.install(entry.id, entry.version)
        return PluginInstallationView(
            pluginId=installation.plugin_id, version=installation.version,
            status="connected" if entry.id in _FIRST_PARTY_UI_PLUGIN_IDS else "available",
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
        if plugin_id in _FIRST_PARTY_UI_PLUGIN_IDS and self.plugin_install_root is not None:
            root = self.plugin_install_root.resolve()
            target = (root / "eeee_chat_history").resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise RuntimeError("plugin install path escaped its root") from exc
            if target.exists():
                shutil.rmtree(target)

    def launch_info(self, plugin_id: str) -> dict[str, object]:
        """Return the installed entrypoint for a separately launched UI plugin."""

        self.catalog_source.get(plugin_id)
        if plugin_id not in _FIRST_PARTY_UI_PLUGIN_IDS:
            raise RuntimeError("this plugin does not expose a desktop UI")
        if not self.installations.is_installed(plugin_id):
            raise RuntimeError("plugin must be installed before opening")
        if self.plugin_install_root is None:
            raise RuntimeError("plugin launch is unavailable")
        root = self.plugin_install_root.resolve()
        entrypoint = (root / "eeee_chat_history" / "main.py").resolve()
        try:
            entrypoint.relative_to(root)
        except ValueError as exc:
            raise RuntimeError("plugin entrypoint escaped its root") from exc
        if not entrypoint.is_file():
            raise RuntimeError("installed plugin entrypoint is missing")
        return {"pluginId": plugin_id, "entrypoint": str(entrypoint)}

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
        if entry.id in _FIRST_PARTY_UI_PLUGIN_IDS:
            return "connected"
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
        except Exception as exc:
            logger.warning(
                "Plugin connection failed for %s: %s",
                plugin_id,
                type(exc).__name__,
            )
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
            logger.warning(
                "Plugin health check failed for %s: status=%s code=%s",
                plugin_id,
                health.status,
                health.code,
            )
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
            try:
                transient = connector.connect(user_id, _credential_from_json(credential), set(connection.approved_permissions))
                health = connector.health(transient)
            except Exception:
                health = ConnectorHealth(
                    status="unavailable",
                    code="provider_unavailable",
                    reason="Plugin provider health check failed",
                )
            if health.code == "reauthentication_required":
                refreshed = self._refresh_credential(
                    connection, connector, _credential_from_json(credential)
                )
                if refreshed is not None:
                    _, health = refreshed
        status = "connected" if health.status == "healthy" else "failed"
        current = self.connections.get(user_id, plugin_id)
        self.connections.save(current.model_copy(update={
            "status": status, "last_health": health.status, "last_error": None if status == "connected" else health.code,
            "updated_at": _now(),
        }))
        return health

    def _refresh_credential(
        self,
        connection: PluginConnection,
        connector: PluginConnector,
        credential: dict[str, str],
    ) -> tuple[str, ConnectorHealth] | None:
        refresher = getattr(connector, "refresh_credential", None)
        if not callable(refresher) or not credential.get("refresh_token"):
            return None
        try:
            refreshed = refresher(credential)
            if not isinstance(refreshed, Mapping):
                raise ValueError("provider credential refresh returned an invalid value")
            refreshed_credential = {
                key: value for key, value in refreshed.items()
                if isinstance(key, str) and isinstance(value, str)
            }
            if not refreshed_credential.get("access_token"):
                raise ValueError("provider credential refresh returned no access token")
            reference = self.credentials.put(
                connection.user_id,
                connection.plugin_id,
                _credential_json(refreshed_credential),
            )
            transient = connector.connect(
                connection.user_id,
                refreshed_credential,
                set(connection.approved_permissions),
            )
            health = connector.health(transient)
            if health.status != "healthy":
                self.credentials.delete(reference)
                return None
            current = self.connections.get(connection.user_id, connection.plugin_id)
            self.connections.save(current.model_copy(update={
                "credential_ref": reference,
                "status": "connected",
                "last_health": health.status,
                "last_error": None,
                "updated_at": _now(),
            }))
            if current.credential_ref and current.credential_ref != reference:
                self.credentials.delete(current.credential_ref)
            return _credential_json(refreshed_credential), health
        except Exception as exc:
            logger.warning(
                "Plugin credential refresh failed for %s: %s",
                connection.plugin_id,
                type(exc).__name__,
            )
            return None

    def capabilities(self, user_id: str = "local-user") -> list[CapabilityDescriptor]:
        projected: list[CapabilityDescriptor] = []
        for entry in self.catalog_source.list():
            if not self.installations.is_installed(entry.id):
                continue
            try:
                connection = self.connections.get(user_id, entry.id)
            except KeyError:
                continue
            if connection.status not in {"connected", "failed"}:
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

    def invoke(
        self,
        user_id: str,
        capability_id: str,
        value: dict[str, object],
        *,
        approval_envelope: ExecutionEnvelope | None = None,
    ) -> ExecutionEnvelope:
        descriptors = {item.id: item for item in self.capabilities(user_id)}
        descriptor = descriptors.get(capability_id)
        if descriptor is None:
            return _blocked_envelope(capability_id, "plugin capability is not connected and healthy")
        plugin_id = capability_id.split(":", 2)[1]
        action = str(value.get("action") or capability_id.rsplit(":", 1)[-1])
        if plugin_id == "notion" and action == "pages":
            action = "get_page"
        context = value.get("context")
        context = context if isinstance(context, dict) else {}
        requires_approval = descriptor.approval_level != "none"
        audit_input = {
            key: item
            for key, item in value.items()
            if key not in {"action", "context", "approved", "approvalRequestId", "text"}
        }
        raw_text = value.get("text")
        try:
            if isinstance(raw_text, str) and raw_text.strip():
                audit_input = {
                    **build_plugin_action_input(plugin_id, action, raw_text),
                    **audit_input,
                }
        except Exception as exc:
            return _blocked_envelope(
                capability_id,
                _sanitize_message(str(exc).strip() or "plugin input could not be understood"),
                error_code="invalid_plugin_input",
            )
        fingerprint = _plugin_approval_fingerprint(user_id, capability_id, action, audit_input)
        approval_request_id = value.get("approvalRequestId") or context.get("approvalRequestId")
        approved = False
        direct_approval = False
        envelope: ExecutionEnvelope | None = None
        if requires_approval and approval_envelope is not None:
            if not (
                approval_envelope.capability_id == capability_id
                and approval_envelope.required_approval
                and approval_envelope.status is ExecutionStatus.RUNNING
                and approval_envelope.approval_state is ApprovalState.APPROVED
            ):
                return _blocked_envelope(
                    capability_id, "plugin approval could not be verified",
                    error_code="invalid_plugin_approval",
                )
            approved = True
        elif requires_approval:
            candidate = None
            if isinstance(approval_request_id, str) and approval_request_id.strip():
                try:
                    candidate = self.executions.get(approval_request_id)
                except KeyError:
                    candidate = None
            same_request = bool(
                candidate is not None
                and candidate.tool_id == plugin_id
                and candidate.capability_id == capability_id
                and candidate.input.get("principal") == user_id
                and candidate.input.get("approvalFingerprint") == fingerprint
            )
            if same_request and candidate.status in {
                ExecutionStatus.COMPLETED, ExecutionStatus.BLOCKED, ExecutionStatus.FAILED,
            }:
                return candidate
            valid_candidate = same_request and candidate.status is ExecutionStatus.AWAITING_APPROVAL
            if valid_candidate and value.get("approved") is True:
                envelope, claimed = self.executions.claim_approval(candidate.execution_id)
                if not claimed:
                    return envelope
                approved = True
                direct_approval = True
            elif valid_candidate:
                return candidate
            else:
                envelope = ExecutionEnvelope(
                    executionId=f"plugin-execution-{uuid4().hex}", requestId=f"plugin-request-{uuid4().hex}",
                    capabilityId=capability_id, toolId=plugin_id, actor="EEEE",
                    input={**audit_input, "principal": user_id, "approvalFingerprint": fingerprint},
                    sideEffectLevel=descriptor.side_effect_level,
                    requiredApproval=True, approvalState=ApprovalState.AWAITING_APPROVAL,
                )
                self.executions.save(envelope)
                waiting = envelope.transition(
                    ExecutionStatus.AWAITING_APPROVAL,
                    output={
                        "status": "awaiting_approval",
                        "message": "메일을 보내기 전에 사용자 승인이 필요해.",
                        "action": action,
                    },
                )
                self.executions.save(waiting)
                return waiting
        if envelope is None:
            envelope = ExecutionEnvelope(
                executionId=f"plugin-execution-{uuid4().hex}", requestId=f"plugin-request-{uuid4().hex}",
                capabilityId=capability_id, toolId=plugin_id, actor="EEEE", input=audit_input,
                sideEffectLevel=descriptor.side_effect_level,
                requiredApproval=requires_approval,
                approvalState=ApprovalState.APPROVED if approved else ApprovalState.NOT_REQUIRED,
            )
        connection = self.connections.get(user_id, plugin_id)
        credential = self.credentials.get(connection.credential_ref) if connection.credential_ref else None
        if credential is None:
            return _blocked_envelope(capability_id, "plugin credential is unavailable", error_code="credential_unavailable")
        try:
            connector = self._connector(plugin_id)
            transient = connector.connect(user_id, _credential_from_json(credential), set(connection.approved_permissions))
            output = _redact_value(connector.invoke(transient, action, audit_input))
            if not isinstance(output, dict):
                output = {"result": output}
            running = envelope if envelope.status is ExecutionStatus.RUNNING else envelope.transition(
                ExecutionStatus.RUNNING,
                approval_state=ApprovalState.APPROVED if requires_approval else ApprovalState.NOT_REQUIRED,
            )
            completed = running.transition(ExecutionStatus.COMPLETED, output=output)
            if direct_approval:
                self.executions.save(completed)
            return completed
        except Exception:
            return _blocked_envelope(
                capability_id, "plugin provider failed while running the action",
                error_code="plugin_provider_failed",
            )

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


def _blocked_envelope(
    capability_id: str,
    message: str,
    *,
    error_code: str = "plugin_blocked",
) -> ExecutionEnvelope:
    envelope = ExecutionEnvelope(
        executionId=f"plugin-execution-{uuid4().hex}", requestId=f"plugin-request-{uuid4().hex}",
        capabilityId=capability_id, toolId="plugin", actor="EEEE", input={},
    )
    return envelope.transition(
        ExecutionStatus.BLOCKED,
        output={"status": "blocked", "message": message},
        error=ExecutionError(code=error_code, message=message),
    )


_SENSITIVE_KEYS = {
    "access_token", "refresh_token", "client_secret", "api_key", "apikey",
    "authorization", "cookie", "password", "secret", "credential", "token",
}


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if str(key).casefold().replace("-", "_") in _SENSITIVE_KEYS
            else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_message(value)
    return value


def _sanitize_message(message: str) -> str:
    sanitized = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", message)
    return re.sub(
        r"(?i)((?:access|refresh)?_?(?:token|secret|password)|api[_-]?key|authorization)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        sanitized,
    )


def _plugin_approval_fingerprint(
    user_id: str, capability_id: str, action: str, audit_input: Mapping[str, object]
) -> str:
    payload = {
        "userId": user_id, "capabilityId": capability_id, "action": action,
        "input": dict(audit_input),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
