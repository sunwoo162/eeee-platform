from __future__ import annotations

import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterator
from uuid import uuid4

from app.knowledge.models import KnowledgeDocument


MAX_DOCUMENT_BYTES = 500_000
MAX_SEARCH_RESULTS = 20


class KnowledgeStore:
    """Durable local documents kept separate from conversational memory."""

    _init_locks: dict[str, threading.Lock] = {}
    _init_locks_guard = threading.Lock()

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.init()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_key = str(self.path.resolve())
        with self._init_locks_guard:
            lock = self._init_locks.setdefault(lock_key, threading.Lock())
        # Multiple requests can construct a store for the same database at
        # once.  Serialize schema/WAL setup in-process; SQLite's busy timeout
        # still handles a writer in another process.
        with lock:
            with self._session() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS local_documents (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        source_path TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        deleted_at TEXT,
                        UNIQUE(scope, content_hash)
                    );
                    CREATE INDEX IF NOT EXISTS idx_local_documents_scope_updated
                        ON local_documents (scope, updated_at DESC);
                    """
                )

    def save_text(
        self, title: str, content: str, *, scope: str = "global", source_path: str | None = None
    ) -> KnowledgeDocument:
        title = title.strip()
        content = content.strip()
        scope = scope.strip()
        if not title or not content or not scope:
            raise ValueError("document title, content, and scope are required")
        if len(content.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ValueError("document is too large")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        now = _iso(_now())
        with self._session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM local_documents WHERE scope = ? AND content_hash = ?",
                (scope, content_hash),
            ).fetchone()
            if existing is not None:
                if existing["deleted_at"] is None:
                    return _document_from_row(existing)
                connection.execute(
                    "UPDATE local_documents SET title = ?, content = ?, source_path = ?, "
                    "updated_at = ?, deleted_at = NULL WHERE id = ?",
                    (title, content, source_path, now, existing["id"]),
                )
                row = connection.execute(
                    "SELECT * FROM local_documents WHERE id = ?", (existing["id"],)
                ).fetchone()
                assert row is not None
                return _document_from_row(row)
            document_id = f"document-{uuid4().hex}"
            try:
                connection.execute(
                    "INSERT INTO local_documents "
                    "(id, title, content, scope, content_hash, source_path, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (document_id, title, content, scope, content_hash, source_path, now, now),
                )
            except sqlite3.IntegrityError:
                # A legacy database may race with another writer between the
                # read and insert, or contain a row created by an older
                # process. Re-read the unique key and make the operation
                # idempotent instead of leaking sqlite errors to the user.
                existing = connection.execute(
                    "SELECT * FROM local_documents WHERE scope = ? AND content_hash = ?",
                    (scope, content_hash),
                ).fetchone()
                if existing is None:
                    raise
                if existing["deleted_at"] is not None:
                    connection.execute(
                        "UPDATE local_documents SET title = ?, content = ?, source_path = ?, "
                        "updated_at = ?, deleted_at = NULL WHERE id = ?",
                        (title, content, source_path, now, existing["id"]),
                    )
                row = connection.execute(
                    "SELECT * FROM local_documents WHERE id = ?", (existing["id"],)
                ).fetchone()
                assert row is not None
                return _document_from_row(row)
            row = connection.execute(
                "SELECT * FROM local_documents WHERE id = ?", (document_id,)
            ).fetchone()
        assert row is not None
        return _document_from_row(row)

    def list(self, *, scope: str = "global", limit: int = 20) -> list[KnowledgeDocument]:
        if limit < 1 or limit > MAX_SEARCH_RESULTS:
            raise ValueError(f"limit must be between 1 and {MAX_SEARCH_RESULTS}")
        with self._session() as connection:
            rows = connection.execute(
                "SELECT * FROM local_documents WHERE scope = ? AND deleted_at IS NULL "
                "ORDER BY updated_at DESC LIMIT ?",
                (scope, limit),
            ).fetchall()
        return [_document_from_row(row) for row in rows]

    def search(self, query: str, *, scope: str = "global", limit: int = 10) -> list[KnowledgeDocument]:
        query = query.strip()
        if not query:
            return self.list(scope=scope, limit=limit)
        if limit < 1 or limit > MAX_SEARCH_RESULTS:
            raise ValueError(f"limit must be between 1 and {MAX_SEARCH_RESULTS}")
        pattern = f"%{_escape_like(query)}%"
        with self._session() as connection:
            rows = connection.execute(
                "SELECT * FROM local_documents WHERE scope = ? AND deleted_at IS NULL "
                "AND (title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\') "
                "ORDER BY updated_at DESC LIMIT ?",
                (scope, pattern, pattern, limit),
            ).fetchall()
        return [_document_from_row(row, query=query) for row in rows]


def _document_from_row(row: sqlite3.Row, *, query: str | None = None) -> KnowledgeDocument:
    content = str(row["content"])
    return KnowledgeDocument(
        id=str(row["id"]), title=str(row["title"]), content=content,
        scope=str(row["scope"]), content_hash=str(row["content_hash"]),
        created_at=_parse_time(str(row["created_at"])),
        updated_at=_parse_time(str(row["updated_at"])),
        source_path=str(row["source_path"]) if row["source_path"] is not None else None,
        snippet=_snippet(content, query) if query else None,
    )


def _snippet(content: str, query: str) -> str:
    lowered = content.casefold()
    position = lowered.find(query.casefold())
    if position < 0:
        return content[:240]
    start = max(0, position - 100)
    end = min(len(content), position + len(query) + 140)
    prefix = "…" if start else ""
    suffix = "…" if end < len(content) else ""
    return prefix + content[start:end].replace("\n", " ") + suffix


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)

