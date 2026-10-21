from __future__ import annotations

import sqlite3


LATEST_SCHEMA_VERSION = 3


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    current = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()[0]
    if current < 1:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived_at TEXT
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL,
                client_message_id TEXT,
                request_id TEXT,
                provider TEXT,
                model TEXT,
                error_code TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(conversation_id, sequence),
                UNIQUE(conversation_id, client_message_id)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS assistant_requests (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                user_message_id TEXT NOT NULL REFERENCES messages(id),
                client_message_id TEXT NOT NULL,
                state TEXT NOT NULL,
                parent_request_id TEXT,
                attempt INTEGER NOT NULL DEFAULT 1,
                error_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                interrupted_at TEXT
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS assistant_events (
                event_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL REFERENCES assistant_requests(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(request_id, sequence)
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_updated_at "
            "ON conversations(updated_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation_sequence "
            "ON messages(conversation_id, sequence)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_requests_state "
            "ON assistant_requests(state, updated_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_request_sequence "
            "ON assistant_events(request_id, sequence)"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
        current = 1
    if current < 2:
        # The request key is the durable idempotency boundary. Keep this as an
        # index migration so databases created by v1 receive the same guard.
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_client_message "
            "ON assistant_requests(conversation_id, client_message_id)"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
        current = 2
    if current < 3:
        # The assistant transcript moved from MemoryStore.conversation_turns
        # to the canonical conversations/messages tables.  Existing installs
        # must keep their history when the new store becomes authoritative.
        legacy_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'conversation_turns'"
        ).fetchone()
        if legacy_table is not None:
            legacy_rows = connection.execute(
                "SELECT conversation_id, role, content, request_id, created_at "
                "FROM conversation_turns ORDER BY conversation_id, id"
            ).fetchall()
            sequence_by_conversation: dict[str, int] = {}
            for row in legacy_rows:
                conversation_id = str(row["conversation_id"])
                connection.execute(
                    "INSERT OR IGNORE INTO conversations "
                    "(id, title, created_at, updated_at, archived_at) VALUES (?, ?, ?, ?, NULL)",
                    (conversation_id, "새 대화", row["created_at"], row["created_at"]),
                )
                sequence = sequence_by_conversation.get(conversation_id)
                if sequence is None:
                    sequence = connection.execute(
                        "SELECT COALESCE(MAX(sequence), 0) FROM messages WHERE conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()[0]
                sequence += 1
                sequence_by_conversation[conversation_id] = sequence
                request_id = row["request_id"]
                already_present = None
                if request_id is not None:
                    already_present = connection.execute(
                        "SELECT 1 FROM messages WHERE conversation_id = ? "
                        "AND request_id = ? AND role = ? LIMIT 1",
                        (conversation_id, request_id, row["role"]),
                    ).fetchone()
                if already_present is not None:
                    continue
                message_id = f"message-legacy-{conversation_id}-{sequence}"
                connection.execute(
                    "INSERT OR IGNORE INTO messages "
                    "(id, conversation_id, sequence, role, content, status, client_message_id, "
                    "request_id, provider, model, error_code, created_at, completed_at) "
                    "VALUES (?, ?, ?, ?, ?, 'completed', NULL, ?, NULL, NULL, NULL, ?, ?)",
                    (
                        message_id, conversation_id, sequence, row["role"], row["content"],
                        request_id, row["created_at"], row["created_at"],
                    ),
                )
                connection.execute(
                    "UPDATE conversations SET updated_at = MAX(updated_at, ?) WHERE id = ?",
                    (row["created_at"], conversation_id),
                )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (3, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
    # Keep the idempotency guard self-healing even if an operator restored a
    # database with the schema marker intact but the index missing.
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_client_message "
        "ON assistant_requests(conversation_id, client_message_id)"
    )
