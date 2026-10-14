from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.storage.connection import connect_sqlite


class ClaimLatchAuditConflictError(RuntimeError):
    """A verification key was reused with different content or metadata."""


class ClaimLatchAuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    audit_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    project_revision: str = Field(min_length=1)
    subject_type: str = Field(min_length=1)
    decision: Literal["PASS", "WARN", "BLOCK"]
    claim_latch_report_id: str = Field(min_length=1)
    receipt_id: str | None = None
    payload_hash: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    claim_latch_version: str = Field(min_length=1)
    claim_latch_profile_version: str = Field(
        default="claimlatch-v0.2.0", min_length=1
    )
    request_payload: dict[str, Any]
    envelope: dict[str, Any]
    created_at: datetime


class ClaimLatchAuditStore:
    """Durable, append-only-ish audit index for ClaimLatch decisions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = connect_sqlite(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS claimlatch_audits (
                    audit_id TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    project_revision TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    claim_latch_report_id TEXT NOT NULL,
                    receipt_id TEXT,
                    payload_hash TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    adapter_version TEXT NOT NULL,
                    claim_latch_version TEXT NOT NULL,
                    claim_latch_profile_version TEXT NOT NULL DEFAULT 'claimlatch-v0.2.0',
                    request_payload_json TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (project_id, subject_id, project_revision)
                );
                CREATE INDEX IF NOT EXISTS idx_claimlatch_project_revision
                    ON claimlatch_audits (project_id, project_revision);
                CREATE INDEX IF NOT EXISTS idx_claimlatch_report
                    ON claimlatch_audits (claim_latch_report_id);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(claimlatch_audits)")
            }
            if "claim_latch_profile_version" not in columns:
                connection.execute(
                    "ALTER TABLE claimlatch_audits ADD COLUMN "
                    "claim_latch_profile_version TEXT NOT NULL "
                    "DEFAULT 'claimlatch-v0.2.0'"
                )

    def save(self, record: ClaimLatchAuditRecord) -> ClaimLatchAuditRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM claimlatch_audits WHERE project_id = ? "
                "AND subject_id = ? AND project_revision = ?",
                (record.project_id, record.subject_id, record.project_revision),
            ).fetchone()
            if existing is not None:
                current = _record_from_row(existing)
                same_metadata = (
                    current.policy_version == record.policy_version
                    and current.adapter_version == record.adapter_version
                    and current.claim_latch_version == record.claim_latch_version
                    and current.claim_latch_profile_version
                    == record.claim_latch_profile_version
                )
                same_result = (
                    current.decision == record.decision
                    and current.claim_latch_report_id == record.claim_latch_report_id
                    and current.receipt_id == record.receipt_id
                    and _without_created_at(current.envelope) == _without_created_at(record.envelope)
                )
                if current.payload_hash == record.payload_hash and same_metadata and same_result:
                    return current
                if current.payload_hash == record.payload_hash:
                    raise ClaimLatchAuditConflictError(
                        "ClaimLatch verification replay used different policy or adapter metadata"
                    )
                raise ClaimLatchAuditConflictError(
                    "ClaimLatch verification replay used a different payload"
                )
            try:
                connection.execute(
                    "INSERT INTO claimlatch_audits ("
                    "audit_id, subject_id, project_id, project_revision, subject_type, decision, "
                    "claim_latch_report_id, receipt_id, payload_hash, policy_version, adapter_version, "
                    "claim_latch_version, claim_latch_profile_version, request_payload_json, "
                    "envelope_json, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.audit_id,
                        record.subject_id,
                        record.project_id,
                        record.project_revision,
                        record.subject_type,
                        record.decision,
                        record.claim_latch_report_id,
                        record.receipt_id,
                        record.payload_hash,
                        record.policy_version,
                        record.adapter_version,
                        record.claim_latch_version,
                        record.claim_latch_profile_version,
                        json.dumps(record.request_payload, ensure_ascii=False, sort_keys=True),
                        json.dumps(record.envelope, ensure_ascii=False, sort_keys=True),
                        _iso(record.created_at),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ClaimLatchAuditConflictError(
                    "ClaimLatch audit ID was reused with different content"
                ) from exc
        return record

    def get(self, audit_id: str) -> ClaimLatchAuditRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM claimlatch_audits WHERE audit_id = ?", (audit_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"ClaimLatch audit not found: {audit_id}")
        return _record_from_row(row)

    def get_for_verification(
        self, project_id: str, subject_id: str, project_revision: str
    ) -> ClaimLatchAuditRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM claimlatch_audits WHERE project_id = ? "
                "AND subject_id = ? AND project_revision = ?",
                (project_id, subject_id, project_revision),
            ).fetchone()
        if row is None:
            raise KeyError(
                "ClaimLatch audit not found for "
                f"{project_id}/{subject_id}/{project_revision}"
            )
        return _record_from_row(row)


def _record_from_row(row: sqlite3.Row) -> ClaimLatchAuditRecord:
    return ClaimLatchAuditRecord(
        audit_id=row["audit_id"],
        subject_id=row["subject_id"],
        project_id=row["project_id"],
        project_revision=row["project_revision"],
        subject_type=row["subject_type"],
        decision=row["decision"],
        claim_latch_report_id=row["claim_latch_report_id"],
        receipt_id=row["receipt_id"],
        payload_hash=row["payload_hash"],
        policy_version=row["policy_version"],
        adapter_version=row["adapter_version"],
        claim_latch_version=row["claim_latch_version"],
        claim_latch_profile_version=row["claim_latch_profile_version"],
        request_payload=json.loads(row["request_payload_json"]),
        envelope=json.loads(row["envelope_json"]),
        created_at=row["created_at"],
    )


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _without_created_at(envelope: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in envelope.items() if key != "createdAt"}
