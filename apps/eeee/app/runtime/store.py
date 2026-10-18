"""SQLite projections of shared execution and plugin lifecycle contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any

from pydantic import BaseModel

from app.contracts import ApprovalState, EventEnvelope, ExecutionEnvelope, ExecutionStatus
from app.plugins.connections import PluginConnection
from app.storage.sqlite import SQLiteStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StaleProjectRevision(ValueError):
    """A project changed after this execution's identity was fixed."""


def _current_project_revision(
    connection: sqlite3.Connection, project_id: str | None, revision: str | None
) -> None:
    if project_id is None:
        return
    row = connection.execute("SELECT revision FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise KeyError(f"Project not found: {project_id}")
    if row["revision"] != revision:
        raise StaleProjectRevision(f"stale project revision for {project_id}: {revision}")


def _is_stale_failure(envelope: ExecutionEnvelope) -> bool:
    if envelope.status not in {ExecutionStatus.FAILED, ExecutionStatus.BLOCKED, ExecutionStatus.CANCELLED}:
        return False
    if envelope.error is None or envelope.error.code != "stale_project_revision":
        return False
    # Stale finalization is a failure observation, never an execution result.
    return envelope.output is None or dict(envelope.output) == {
        "status": "blocked", "message": envelope.error.message,
    }


def _preserves_stale_audit(previous: ExecutionEnvelope, current: ExecutionEnvelope) -> bool:
    return all(getattr(previous, field) == getattr(current, field) for field in (
        "evidence_ids", "claim_latch_receipt_id", "qa_report_id", "approval_state",
    ))


def _ensure_event_identity(execution: ExecutionEnvelope, event: EventEnvelope) -> None:
    if any(getattr(execution, field) != getattr(event, field) for field in (
        "execution_id", "request_id", "project_id", "project_revision",
    )):
        raise ValueError("event and execution identity mismatch")


def _ensure_execution_update(previous: ExecutionEnvelope, current: ExecutionEnvelope) -> None:
    identity = (
        "request_id", "project_id", "project_revision", "capability_id", "tool_id", "actor",
        "input_schema_version", "input", "started_at", "side_effect_level", "required_approval",
    )
    if any(getattr(previous, field) != getattr(current, field) for field in identity):
        raise ValueError("execution identity, input, and approval policy cannot change")
    if current.evidence_ids[: len(previous.evidence_ids)] != previous.evidence_ids:
        raise ValueError("recorded audit evidence cannot be removed or replaced")
    if previous.claim_latch_receipt_id is not None and (
        current.claim_latch_receipt_id != previous.claim_latch_receipt_id
    ):
        raise ValueError("recorded ClaimLatch receipt cannot be removed or replaced")
    if previous.qa_report_id is not None and current.qa_report_id != previous.qa_report_id:
        raise ValueError("recorded QA report cannot be removed or replaced")
    if previous.status in {
        ExecutionStatus.COMPLETED, ExecutionStatus.BLOCKED,
        ExecutionStatus.FAILED, ExecutionStatus.CANCELLED,
    } and previous != current:
        raise ValueError("terminal execution cannot be rewritten")
    if previous.status == current.status:
        return
    # The shared contract owns transition policy. Validate the proposed status
    # with it rather than keeping a second transition matrix in persistence.
    previous.transition(
        current.status,
        at=current.completed_at,
        output=None if current.output is None else dict(current.output),
        error=current.error,
        approval_state=current.approval_state,
    )


class ExecutionStore:
    """Persist envelopes and an ordered, replayable local event ledger."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def save(self, envelope: ExecutionEnvelope) -> ExecutionEnvelope:
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._save(connection, envelope)
        return envelope

    def record(self, envelope: ExecutionEnvelope, event: EventEnvelope) -> EventEnvelope:
        """Commit a state transition and its durable event in one transaction."""
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _ensure_event_identity(envelope, event)
            self._save(connection, envelope)
            return self._append_event(connection, event)

    @staticmethod
    def _save(connection: sqlite3.Connection, envelope: ExecutionEnvelope) -> None:
        row = connection.execute(
            "SELECT envelope_json, created_at FROM execution_envelopes WHERE execution_id = ?",
            (envelope.execution_id,),
        ).fetchone()
        previous = ExecutionEnvelope.model_validate_json(row["envelope_json"]) if row is not None else None
        try:
            _current_project_revision(connection, envelope.project_id, envelope.project_revision)
        except StaleProjectRevision:
            if previous is None or not _is_stale_failure(envelope) or not _preserves_stale_audit(previous, envelope):
                raise
        if previous is not None:
            _ensure_execution_update(previous, envelope)
        timestamp = _now()
        connection.execute(
            "INSERT INTO execution_envelopes "
            "(execution_id, request_id, project_id, project_revision, capability_id, tool_id, "
            "status, envelope_json, started_at, completed_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(execution_id) DO UPDATE SET "
            "status = excluded.status, envelope_json = excluded.envelope_json, "
            "completed_at = excluded.completed_at, updated_at = excluded.updated_at",
            (
                envelope.execution_id, envelope.request_id, envelope.project_id,
                envelope.project_revision, envelope.capability_id, envelope.tool_id,
                envelope.status.value, envelope.model_dump_json(by_alias=True),
                envelope.started_at.isoformat(),
                envelope.completed_at.isoformat() if envelope.completed_at else None,
                row["created_at"] if row is not None else timestamp, timestamp,
            ),
        )

    def get(self, execution_id: str) -> ExecutionEnvelope:
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT envelope_json FROM execution_envelopes WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Execution not found: {execution_id}")
        return ExecutionEnvelope.model_validate_json(row["envelope_json"])

    def list_for_project(self, project_id: str, revision: str | None = None) -> list[ExecutionEnvelope]:
        query = "SELECT envelope_json FROM execution_envelopes WHERE project_id = ?"
        parameters: list[str] = [project_id]
        if revision is not None:
            query += " AND project_revision = ?"
            parameters.append(revision)
        query += " ORDER BY started_at, created_at, rowid"
        with self.store._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [ExecutionEnvelope.model_validate_json(row["envelope_json"]) for row in rows]

    def claim_approval(self, execution_id: str) -> tuple[ExecutionEnvelope, bool]:
        """Atomically claim an approval execution exactly once."""
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT envelope_json FROM execution_envelopes WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Execution not found: {execution_id}")
            current = ExecutionEnvelope.model_validate_json(row["envelope_json"])
            if current.status is not ExecutionStatus.AWAITING_APPROVAL:
                return current, False
            claimed = current.transition(
                ExecutionStatus.RUNNING,
                approval_state=ApprovalState.APPROVED,
            )
            self._save(connection, claimed)
            return claimed, True

    def list_plugin_routes(self, *, limit: int = 20) -> list[ExecutionEnvelope]:
        """Return recent EEEE-routed plugin executions without raw inputs."""
        if limit < 1:
            raise ValueError("limit must be positive")
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT envelope_json FROM execution_envelopes "
                "WHERE tool_id = 'eeee.route' AND capability_id LIKE 'plugin:%' "
                "ORDER BY started_at DESC, created_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [ExecutionEnvelope.model_validate_json(row["envelope_json"]) for row in rows]

    def append_event(self, event: EventEnvelope) -> EventEnvelope:
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._append_event(connection, event)

    @staticmethod
    def _append_event(connection: sqlite3.Connection, event: EventEnvelope) -> EventEnvelope:
        execution = connection.execute(
            "SELECT request_id, project_id, project_revision, envelope_json FROM execution_envelopes "
            "WHERE execution_id = ?", (event.execution_id,),
        ).fetchone()
        stored = ExecutionEnvelope.model_validate_json(execution["envelope_json"]) if execution else None
        try:
            _current_project_revision(connection, event.project_id, event.project_revision)
        except StaleProjectRevision:
            if (stored is None or not _is_stale_failure(stored)
                or event.event_type != f"execution.{stored.status.value}"
                or dict(event.payload) != {
                    "status": stored.status.value, "toolId": stored.tool_id,
                    "parentExecutionId": stored.input.get("parentExecutionId"),
                }):
                raise
        if stored is None:
            raise KeyError(f"Execution not found: {event.execution_id}")
        _ensure_event_identity(stored, event)
        cursor = connection.execute(
            "INSERT INTO execution_events "
            "(execution_id, request_id, project_id, project_revision, event_type, event_json, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event.execution_id, event.request_id, event.project_id,
                event.project_revision, event.event_type, event.model_dump_json(by_alias=True),
                event.published_at.isoformat(),
            ),
        ).lastrowid
        published = EventEnvelope.model_validate({**event.model_dump(), "cursor": cursor})
        connection.execute(
            "UPDATE execution_events SET event_json = ? WHERE cursor = ?",
            (published.model_dump_json(by_alias=True), cursor),
        )
        return published

    def replay_events(
        self, *, after_cursor: int = 0, project_id: str | None = None,
        revision: str | None = None, limit: int | None = None,
    ) -> list[EventEnvelope]:
        if after_cursor < 0 or limit is not None and limit < 1:
            raise ValueError("cursor must be nonnegative and limit must be positive")
        if revision is not None and project_id is None:
            raise ValueError("revision filter requires project ID")
        query = "SELECT event_json FROM execution_events WHERE cursor > ?"
        parameters: list[int | str] = [after_cursor]
        if project_id is not None:
            query += " AND project_id = ?"
            parameters.append(project_id)
        if revision is not None:
            query += " AND project_revision = ?"
            parameters.append(revision)
        query += " ORDER BY cursor"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.store._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [EventEnvelope.model_validate_json(row["event_json"]) for row in rows]


@dataclass(frozen=True)
class PluginRegistration:
    plugin_id: str
    manifest_version: str
    manifest: dict[str, Any]
    status: str
    created_at: str
    updated_at: str
    removed_at: str | None = None


_PLUGIN_STATUSES = frozenset(
    {
        "available",
        "not_installed",
        "installed",
        "awaiting_authentication",
        "auth_required",
        "connected",
        "ready",
        "running",
        "degraded",
        "disabled",
        "failed",
        "removed",
        "connecting",
        "paused",
    }
)


def _registration_from_row(row: sqlite3.Row) -> PluginRegistration:
    return PluginRegistration(
        plugin_id=row["plugin_id"], manifest_version=row["manifest_version"],
        manifest=json.loads(row["manifest_json"]), status=row["status"],
        created_at=row["created_at"], updated_at=row["updated_at"], removed_at=row["removed_at"],
    )


def _manifest_data(manifest: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
    if isinstance(manifest, BaseModel):
        data = manifest.model_dump(mode="json", by_alias=True)
    elif isinstance(manifest, Mapping):
        data = dict(manifest)
    else:
        raise TypeError("plugin manifest must be a mapping or Pydantic model")
    if not isinstance(data.get("id"), str) or not data["id"].strip():
        raise ValueError("plugin manifest id is required")
    if not isinstance(data.get("version"), str) or not data["version"].strip():
        raise ValueError("plugin manifest version is required")
    return json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False))


class PluginRegistrationStore:
    """Soft-delete plugin registrations while retaining lifecycle audit rows."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    @staticmethod
    def _audit(
        connection: sqlite3.Connection, plugin_id: str, action: str, status: str,
        manifest_version: str, occurred_at: str,
    ) -> None:
        connection.execute(
            "INSERT INTO plugin_audit_events "
            "(plugin_id, action, status, manifest_version, event_json, occurred_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                plugin_id, action, status, manifest_version,
                json.dumps({"pluginId": plugin_id, "action": action, "status": status,
                            "manifestVersion": manifest_version, "occurredAt": occurred_at}),
                occurred_at,
            ),
        )

    def register(self, manifest: Mapping[str, Any] | BaseModel) -> PluginRegistration:
        data = _manifest_data(manifest)
        plugin_id, version = data["id"], data["version"]
        timestamp = _now()
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT removed_at FROM plugin_registrations WHERE plugin_id = ?", (plugin_id,)
            ).fetchone()
            if prior is not None and prior["removed_at"] is None:
                raise ValueError(f"plugin already registered: {plugin_id}")
            if prior is None:
                connection.execute(
                    "INSERT INTO plugin_registrations "
                    "(plugin_id, manifest_version, status, manifest_json, created_at, updated_at, removed_at) "
                    "VALUES (?, ?, 'available', ?, ?, ?, NULL)",
                    (plugin_id, version, json.dumps(data, ensure_ascii=False, sort_keys=True), timestamp, timestamp),
                )
            else:
                connection.execute(
                    "UPDATE plugin_registrations SET manifest_version = ?, status = 'available', "
                    "manifest_json = ?, created_at = ?, updated_at = ?, removed_at = NULL "
                    "WHERE plugin_id = ?",
                    (version, json.dumps(data, ensure_ascii=False, sort_keys=True), timestamp, timestamp, plugin_id),
                )
            self._audit(connection, plugin_id, "registered", "available", version, timestamp)
            row = connection.execute(
                "SELECT * FROM plugin_registrations WHERE plugin_id = ?", (plugin_id,)
            ).fetchone()
        return _registration_from_row(row)

    def get(self, plugin_id: str) -> PluginRegistration:
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM plugin_registrations WHERE plugin_id = ? AND removed_at IS NULL",
                (plugin_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Plugin not found: {plugin_id}")
        return _registration_from_row(row)

    def list(self, status: str | None = None) -> list[PluginRegistration]:
        if status is not None and status not in _PLUGIN_STATUSES:
            raise ValueError(f"invalid plugin status: {status}")
        query = "SELECT * FROM plugin_registrations WHERE removed_at IS NULL"
        parameters: tuple[str, ...] = ()
        if status is not None:
            query += " AND status = ?"
            parameters = (status,)
        query += " ORDER BY plugin_id"
        with self.store._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_registration_from_row(row) for row in rows]

    def set_status(self, plugin_id: str, status: str) -> PluginRegistration:
        if status not in _PLUGIN_STATUSES:
            raise ValueError(f"invalid plugin status: {status}")
        timestamp = _now()
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM plugin_registrations WHERE plugin_id = ? AND removed_at IS NULL",
                (plugin_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Plugin not found: {plugin_id}")
            connection.execute(
                "UPDATE plugin_registrations SET status = ?, updated_at = ? WHERE plugin_id = ?",
                (status, timestamp, plugin_id),
            )
            self._audit(connection, plugin_id, f"status:{status}", status, row["manifest_version"], timestamp)
            updated = connection.execute(
                "SELECT * FROM plugin_registrations WHERE plugin_id = ?", (plugin_id,)
            ).fetchone()
        return _registration_from_row(updated)

    def remove(self, plugin_id: str) -> None:
        timestamp = _now()
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT manifest_version FROM plugin_registrations "
                "WHERE plugin_id = ? AND removed_at IS NULL", (plugin_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Plugin not found: {plugin_id}")
            connection.execute(
                "UPDATE plugin_registrations SET status = 'removed', updated_at = ?, removed_at = ? "
                "WHERE plugin_id = ?", (timestamp, timestamp, plugin_id),
            )
            self._audit(connection, plugin_id, "removed", "removed", row["manifest_version"], timestamp)


@dataclass(frozen=True)
class PluginInstallation:
    plugin_id: str
    version: str
    installed_at: str
    updated_at: str
    removed_at: str | None = None


def _installation_from_row(row: sqlite3.Row) -> PluginInstallation:
    return PluginInstallation(
        plugin_id=row["plugin_id"], version=row["version"],
        installed_at=row["installed_at"], updated_at=row["updated_at"],
        removed_at=row["removed_at"],
    )


class PluginInstallationStore:
    """Persist optional catalog installation state independently of local manifests."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def install(self, plugin_id: str, version: str) -> PluginInstallation:
        if not plugin_id.strip() or not version.strip():
            raise ValueError("plugin id and version are required")
        timestamp = _now()
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO plugin_installations (plugin_id, version, installed_at, updated_at, removed_at) "
                "VALUES (?, ?, ?, ?, NULL) ON CONFLICT(plugin_id) DO UPDATE SET version = excluded.version, "
                "updated_at = excluded.updated_at, removed_at = NULL",
                (plugin_id, version, timestamp, timestamp),
            )
            row = connection.execute(
                "SELECT * FROM plugin_installations WHERE plugin_id = ?", (plugin_id,)
            ).fetchone()
        return _installation_from_row(row)

    def get(self, plugin_id: str) -> PluginInstallation:
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM plugin_installations WHERE plugin_id = ? AND removed_at IS NULL",
                (plugin_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Plugin installation not found: {plugin_id}")
        return _installation_from_row(row)

    def is_installed(self, plugin_id: str) -> bool:
        try:
            self.get(plugin_id)
        except KeyError:
            return False
        return True

    def list(self) -> list[PluginInstallation]:
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM plugin_installations WHERE removed_at IS NULL ORDER BY plugin_id"
            ).fetchall()
        return [_installation_from_row(row) for row in rows]

    def remove(self, plugin_id: str) -> None:
        timestamp = _now()
        with self.store._connect() as connection:
            connection.execute(
                "UPDATE plugin_installations SET removed_at = ?, updated_at = ? "
                "WHERE plugin_id = ? AND removed_at IS NULL",
                (timestamp, timestamp, plugin_id),
            )


class PluginConnectionStore:
    """Persist only redacted user-scoped connection projections."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def save(self, connection: PluginConnection) -> PluginConnection:
        with self.store._connect() as database:
            database.execute(
                "INSERT INTO plugin_connections (user_id, plugin_id, status, approved_permissions_json, "
                "credential_ref, account_label, last_health, last_error, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, plugin_id) DO UPDATE SET status = excluded.status, "
                "approved_permissions_json = excluded.approved_permissions_json, credential_ref = excluded.credential_ref, "
                "account_label = excluded.account_label, last_health = excluded.last_health, "
                "last_error = excluded.last_error, updated_at = excluded.updated_at",
                (
                    connection.user_id, connection.plugin_id, connection.status,
                    json.dumps(connection.approved_permissions, ensure_ascii=False),
                    connection.credential_ref, connection.account_label,
                    connection.last_health, connection.last_error, connection.updated_at,
                ),
            )
        return connection

    def get(self, user_id: str, plugin_id: str) -> PluginConnection:
        with self.store._connect() as database:
            row = database.execute(
                "SELECT * FROM plugin_connections WHERE user_id = ? AND plugin_id = ?",
                (user_id, plugin_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Plugin connection not found: {plugin_id}")
        return PluginConnection(
            userId=row["user_id"], pluginId=row["plugin_id"], status=row["status"],
            approvedPermissions=json.loads(row["approved_permissions_json"]),
            credentialRef=row["credential_ref"], accountLabel=row["account_label"],
            lastHealth=row["last_health"], lastError=row["last_error"], updatedAt=row["updated_at"],
        )

    def list(self, user_id: str) -> list[PluginConnection]:
        with self.store._connect() as database:
            rows = database.execute(
                "SELECT * FROM plugin_connections WHERE user_id = ? ORDER BY plugin_id", (user_id,)
            ).fetchall()
        return [self.get(user_id, row["plugin_id"]) for row in rows]

    def list_all(self) -> list[PluginConnection]:
        with self.store._connect() as database:
            rows = database.execute(
                "SELECT user_id, plugin_id FROM plugin_connections ORDER BY user_id, plugin_id"
            ).fetchall()
        return [self.get(row["user_id"], row["plugin_id"]) for row in rows]

    def remove(self, user_id: str, plugin_id: str) -> None:
        with self.store._connect() as database:
            database.execute(
                "DELETE FROM plugin_connections WHERE user_id = ? AND plugin_id = ?",
                (user_id, plugin_id),
            )
