from __future__ import annotations

import sqlite3


LATEST_SCHEMA_VERSION = 1


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
