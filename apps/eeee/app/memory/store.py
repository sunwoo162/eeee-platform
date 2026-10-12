from __future__ import annotations

import json
import sqlite3
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.memory.models import MemoryCandidate, MemoryRecord, MemoryStatus


_CONVERSATION_SECRET_PATTERN = re.compile(
    r"((?:api[_ -]?key|apikey|access[_ -]?token|refresh[_ -]?token|password|비밀번호|토큰|secret)\s*[:=]\s*)[^\s,]+",
    re.IGNORECASE,
)


class MemoryConflictError(RuntimeError):
    """A candidate ID was reused for different content."""


class MemoryPromotionError(RuntimeError):
    """A memory lifecycle transition is not allowed."""


class MemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    source_project_id TEXT NOT NULL,
                    source_artifact_ids_json TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    verification_ids_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_verified_at TEXT,
                    expires_at TEXT,
                    superseded_by_id TEXT,
                    approved_by TEXT,
                    user_editable INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_records (status);
                CREATE INDEX IF NOT EXISTS idx_memory_project ON memory_records (source_project_id);
                CREATE INDEX IF NOT EXISTS idx_conversation_turns_lookup
                    ON conversation_turns (conversation_id, id);
                """
            )

    def append_conversation_turn(self, conversation_id: str, role: str, content: str) -> None:
        """Persist one local conversation turn for short-term continuity."""

        conversation_id = conversation_id.strip()
        content = _redact_conversation_content(content.strip())
        if not conversation_id:
            raise ValueError("conversation_id is required")
        if role not in {"user", "assistant"}:
            raise ValueError("conversation role must be user or assistant")
        if not content:
            raise ValueError("conversation content is required")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO conversation_turns "
                "(conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, _iso(_now())),
            )

    def recent_conversation_turns(
        self, conversation_id: str, *, limit: int = 12
    ) -> list[dict[str, str]]:
        """Return the latest turns in chronological order for provider context."""

        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT role, content FROM conversation_turns "
                "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [
            {"role": str(row["role"]), "content": str(row["content"])}
            for row in reversed(rows)
        ]

    def save_candidate(self, candidate: MemoryCandidate) -> MemoryRecord:
        record = MemoryRecord(
            id=candidate.candidate_id,
            kind=candidate.kind,
            content=candidate.content,
            scope=candidate.scope,
            source_project_id=candidate.source_project_id,
            source_artifact_ids=candidate.source_artifact_ids,
            evidence_ids=candidate.evidence_ids,
            verification_ids=candidate.verification_ids,
            confidence=candidate.confidence,
            status=MemoryStatus.CANDIDATE,
            created_at=candidate.created_at,
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM memory_records WHERE id = ?", (record.id,)
            ).fetchone()
            if existing is not None:
                current = _record_from_row(existing)
                if current != record:
                    raise MemoryConflictError(
                        f"Memory candidate {record.id} already exists with different content"
                    )
                return current
            _insert_record(connection, record)
            _append_event(connection, record.id, "candidate_created", "system", {})
        return record

    def save_user_preference(
        self, key: str, value: str, *, scope: dict[str, Any] | None = None
    ) -> MemoryRecord:
        """Persist an explicit user preference as the sole active value for its key."""

        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError("user preference key and value are required")
        preference_scope = {"preferenceKey": key, **(scope or {})}
        digest = hashlib.sha256(f"{key}\0{value}".encode("utf-8")).hexdigest()
        record = MemoryRecord(
            id=f"user-preference-{digest[:24]}",
            kind="user_preference",
            content=value,
            scope=preference_scope,
            source_project_id="user",
            source_artifact_ids=[f"user-preference:{key}"],
            evidence_ids=[f"user-stated:{key}"],
            verification_ids=[f"user-stated:{key}"],
            confidence=1.0,
            status=MemoryStatus.ACTIVE,
            created_at=_now(),
            last_verified_at=_now(),
            approved_by="user",
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_rows = connection.execute(
                "SELECT * FROM memory_records WHERE kind = ? AND status = ?",
                ("user_preference", MemoryStatus.ACTIVE.value),
            ).fetchall()
            old_records = [
                _record_from_row(row)
                for row in existing_rows
                if json.loads(row["scope_json"]).get("preferenceKey") == key
            ]
            if any(old.content == value for old in old_records):
                return next(old for old in old_records if old.content == value)
            _insert_record(connection, record)
            _append_event(connection, record.id, "candidate_created", "user", {"key": key})
            _append_event(connection, record.id, "promoted", "user", {"reason": "explicit user preference"})
            for old in old_records:
                connection.execute(
                    "UPDATE memory_records SET status = ?, superseded_by_id = ? WHERE id = ?",
                    (MemoryStatus.SUPERSEDED.value, record.id, old.id),
                )
                _append_event(connection, old.id, "superseded", "user", {"replacementId": record.id})
        return record

    def search_user_preferences(self) -> dict[str, MemoryRecord]:
        records = [record for record in self.search("", limit=1000) if record.kind == "user_preference"]
        return {
            str(record.scope["preferenceKey"]): record
            for record in records
            if isinstance(record.scope.get("preferenceKey"), str)
        }

    def get(self, memory_id: str) -> MemoryRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_records WHERE id = ?", (memory_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Memory not found: {memory_id}")
        return _record_from_row(row)

    def list_records(
        self,
        *,
        status: MemoryStatus | str | None = None,
        source_project_id: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        status_value = status.value if isinstance(status, MemoryStatus) else status
        if status_value is not None:
            try:
                status_value = MemoryStatus(status_value).value
            except ValueError as exc:
                raise ValueError(f"Unknown memory status: {status_value}") from exc
        clauses: list[str] = []
        params: list[object] = []
        if status_value is not None:
            clauses.append("status = ?")
            params.append(status_value)
        if source_project_id is not None:
            clauses.append("source_project_id = ?")
            params.append(source_project_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_records" + where + " ORDER BY created_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def delete(self, memory_id: str, *, actor: str, reason: str) -> MemoryRecord:
        if not actor.strip():
            raise MemoryPromotionError("Deletion requires an actor")
        if not reason.strip():
            raise MemoryPromotionError("Deletion requires a reason")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM memory_records WHERE id = ?", (memory_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Memory not found: {memory_id}")
            record = _record_from_row(row)
            if not record.user_editable:
                raise MemoryPromotionError("This memory cannot be deleted by the user")
            if record.status in {MemoryStatus.SUPERSEDED, MemoryStatus.REVOKED}:
                raise MemoryPromotionError(
                    f"Cannot delete {record.status.value} memory; preserve lifecycle history"
                )
            _append_event(connection, memory_id, "deleted", actor, {"reason": reason})
            connection.execute("DELETE FROM memory_records WHERE id = ?", (memory_id,))
        return record

    def promote(
        self,
        memory_id: str,
        *,
        actor: str,
        evidence_ids: list[str],
    ) -> MemoryRecord:
        if not actor.strip():
            raise MemoryPromotionError("Promotion requires an actor")
        if not evidence_ids:
            raise MemoryPromotionError("Promotion requires verification evidence")
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM memory_records WHERE id = ?", (memory_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Memory not found: {memory_id}")
            record = _record_from_row(row)
            if record.status is not MemoryStatus.CANDIDATE:
                raise MemoryPromotionError(
                    f"Only candidate memories can be promoted: {record.status.value}"
                )
            connection.execute(
                "UPDATE memory_records SET status = ?, last_verified_at = ?, "
                "approved_by = ?, evidence_ids_json = ? WHERE id = ?",
                (
                    MemoryStatus.ACTIVE.value,
                    _iso(now),
                    actor,
                    json.dumps(evidence_ids),
                    memory_id,
                ),
            )
            _append_event(connection, memory_id, "promoted", actor, {"evidenceIds": evidence_ids})
            return record.model_copy(
                update={
                    "status": MemoryStatus.ACTIVE,
                    "last_verified_at": now,
                    "approved_by": actor,
                    "evidence_ids": evidence_ids,
                }
            )

    def supersede(self, memory_id: str, replacement_id: str) -> MemoryRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old_row = connection.execute(
                "SELECT * FROM memory_records WHERE id = ?", (memory_id,)
            ).fetchone()
            replacement_row = connection.execute(
                "SELECT * FROM memory_records WHERE id = ?", (replacement_id,)
            ).fetchone()
            if old_row is None:
                raise KeyError(f"Memory not found: {memory_id}")
            if replacement_row is None:
                raise KeyError(f"Memory not found: {replacement_id}")
            old = _record_from_row(old_row)
            replacement = _record_from_row(replacement_row)
            if old.status is not MemoryStatus.ACTIVE:
                raise MemoryPromotionError("Only active memories can be superseded")
            if replacement.status is not MemoryStatus.ACTIVE:
                raise MemoryPromotionError("Replacement memory must be active")
            connection.execute(
                "UPDATE memory_records SET status = ?, superseded_by_id = ? WHERE id = ?",
                (MemoryStatus.SUPERSEDED.value, replacement_id, memory_id),
            )
            _append_event(
                connection,
                memory_id,
                "superseded",
                "system",
                {"replacementId": replacement_id},
            )
            return old.model_copy(
                update={
                    "status": MemoryStatus.SUPERSEDED,
                    "superseded_by_id": replacement_id,
                }
            )

    def revoke(self, memory_id: str, *, reason: str) -> MemoryRecord:
        if not reason.strip():
            raise MemoryPromotionError("Revocation requires a reason")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM memory_records WHERE id = ?", (memory_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Memory not found: {memory_id}")
            record = _record_from_row(row)
            if record.status is MemoryStatus.REVOKED:
                return record
            connection.execute(
                "UPDATE memory_records SET status = ? WHERE id = ?",
                (MemoryStatus.REVOKED.value, memory_id),
            )
            _append_event(connection, memory_id, "revoked", "user", {"reason": reason})
            return record.model_copy(update={"status": MemoryStatus.REVOKED})

    def search(
        self,
        query: str,
        *,
        scope: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        tokens = {token for token in query.lower().split() if token}
        now = _iso(_now())
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_records WHERE status = ? "
                "AND (expires_at IS NULL OR expires_at > ?) ORDER BY confidence DESC, created_at DESC",
                (MemoryStatus.ACTIVE.value, now),
            ).fetchall()
        ranked: list[tuple[int, float, MemoryRecord]] = []
        for row in rows:
            record = _record_from_row(row)
            if scope and any(record.scope.get(key) != value for key, value in scope.items()):
                continue
            haystack = (record.content + " " + " ".join(map(str, record.scope.values()))).lower()
            score = sum(1 for token in tokens if token in haystack)
            if tokens and score == 0:
                continue
            ranked.append((score, record.confidence, record))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [record for _, _, record in ranked[:limit]]


def _insert_record(connection: sqlite3.Connection, record: MemoryRecord) -> None:
    connection.execute(
        "INSERT INTO memory_records (id, kind, content, scope_json, source_project_id, "
        "source_artifact_ids_json, evidence_ids_json, verification_ids_json, confidence, "
        "status, created_at, last_verified_at, expires_at, superseded_by_id, approved_by, user_editable) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record.id,
            record.kind,
            record.content,
            json.dumps(record.scope),
            record.source_project_id,
            json.dumps(record.source_artifact_ids),
            json.dumps(record.evidence_ids),
            json.dumps(record.verification_ids),
            record.confidence,
            record.status.value,
            _iso(record.created_at),
            _iso(record.last_verified_at) if record.last_verified_at else None,
            _iso(record.expires_at) if record.expires_at else None,
            record.superseded_by_id,
            record.approved_by,
            int(record.user_editable),
        ),
    )


def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        kind=row["kind"],
        content=row["content"],
        scope=json.loads(row["scope_json"]),
        source_project_id=row["source_project_id"],
        source_artifact_ids=json.loads(row["source_artifact_ids_json"]),
        evidence_ids=json.loads(row["evidence_ids_json"]),
        verification_ids=json.loads(row["verification_ids_json"]),
        confidence=row["confidence"],
        status=row["status"],
        created_at=row["created_at"],
        last_verified_at=row["last_verified_at"],
        expires_at=row["expires_at"],
        superseded_by_id=row["superseded_by_id"],
        approved_by=row["approved_by"],
        user_editable=bool(row["user_editable"]),
    )


def _append_event(
    connection: sqlite3.Connection,
    memory_id: str,
    event_type: str,
    actor: str,
    detail: dict[str, Any],
) -> None:
    connection.execute(
        "INSERT INTO memory_events (memory_id, event_type, actor, detail_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (memory_id, event_type, actor, json.dumps(detail), _iso(_now())),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _redact_conversation_content(content: str) -> str:
    return _CONVERSATION_SECRET_PATTERN.sub(r"\1[민감정보]", content)
