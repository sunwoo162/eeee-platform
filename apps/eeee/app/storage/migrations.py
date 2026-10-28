from __future__ import annotations

import sqlite3

LATEST_SCHEMA_VERSION = 13


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
        current = 3
    if current < 4:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(conversations)").fetchall()
        }
        if "user_id" not in columns:
            connection.execute(
                "ALTER TABLE conversations ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local-user'"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_user_updated_at "
            "ON conversations(user_id, updated_at DESC)"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (4, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
        current = 4
    if current < 5:
        for table in ("design_packs", "visual_verifications"):
            columns = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "user_id" not in columns:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local-user'"
                )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_design_packs_user "
            "ON design_packs(user_id, id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_visual_verifications_user "
            "ON visual_verifications(user_id, id)"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (5, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
        current = 5
    if current < 6:
        # Project folders are authoritative scope boundaries, never inferred from titles.
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS chat_workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('personal', 'team')),
                owner_user_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_workspace_members (
                workspace_id TEXT NOT NULL REFERENCES chat_workspaces(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('owner', 'editor', 'viewer')),
                PRIMARY KEY (workspace_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_chat_workspace_members_user
                ON chat_workspace_members(user_id, workspace_id);
            CREATE TABLE IF NOT EXISTS chat_projects (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES chat_workspaces(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chat_projects_workspace
                ON chat_projects(workspace_id, id);
            CREATE TABLE IF NOT EXISTS chat_conversation_links (
                conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL REFERENCES chat_projects(id) ON DELETE CASCADE,
                linked_by_user_id TEXT NOT NULL,
                linked_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chat_links_project
                ON chat_conversation_links(project_id, conversation_id);
            CREATE TABLE IF NOT EXISTS chat_project_memories (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES chat_projects(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                created_by_user_id TEXT NOT NULL,
                source_message_id TEXT,
                status TEXT NOT NULL CHECK(status IN ('active','revoked')),
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chat_memories_project_status
                ON chat_project_memories(project_id, status, created_at DESC);
        """)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (6, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
    if current < 7:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(assistant_requests)")
        }
        if "selected_provider" not in columns:
            connection.execute(
                "ALTER TABLE assistant_requests ADD COLUMN selected_provider TEXT "
                "NOT NULL DEFAULT 'auto'"
            )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (7, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
    if current < 8:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS chat_project_directories (
                project_id TEXT PRIMARY KEY REFERENCES chat_projects(id) ON DELETE CASCADE,
                relative_path TEXT NOT NULL,
                bound_by_user_id TEXT NOT NULL,
                bound_at TEXT NOT NULL
            );
        """)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (8, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
    if current < 9:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS codex_agent_tasks (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL REFERENCES chat_projects(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_codex_agent_tasks_owner
                ON codex_agent_tasks(user_id, conversation_id, updated_at DESC);
            CREATE TABLE IF NOT EXISTS codex_agent_audit (
                task_id TEXT NOT NULL REFERENCES codex_agent_tasks(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                PRIMARY KEY (task_id, sequence)
            );
        """)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (9, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
    if current < 10:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS chat_import_sources (
                conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                provider TEXT NOT NULL CHECK(provider IN ('chatgpt','claude','codex')),
                source_id TEXT NOT NULL,
                source_digest TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                UNIQUE(user_id,provider,source_id)
            );
            CREATE INDEX IF NOT EXISTS idx_chat_import_sources_user
                ON chat_import_sources(user_id,provider,imported_at DESC);
        """)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (10, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
    if current < 11:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS chat_memory_reviews (
                project_id TEXT NOT NULL REFERENCES chat_projects(id) ON DELETE CASCADE,
                source_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                reviewed_by TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('approved','dismissed')),
                reviewed_at TEXT NOT NULL,
                memory_id TEXT REFERENCES chat_project_memories(id) ON DELETE SET NULL,
                PRIMARY KEY(project_id,source_message_id)
            );
        """)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (11, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
    if current < 12:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS chat_memory_analyses (
                project_id TEXT NOT NULL REFERENCES chat_projects(id) ON DELETE CASCADE,
                source_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                analyzed_by TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT,
                verdict TEXT NOT NULL CHECK(verdict IN ('new','duplicate','conflict','uncertain')),
                analysis_json TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                PRIMARY KEY(project_id, source_message_id, analyzed_by)
            );
        """)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (12, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
    if current < 13:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS chat_memory_revisions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES chat_projects(id) ON DELETE CASCADE,
                memory_id TEXT NOT NULL REFERENCES chat_project_memories(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                action TEXT NOT NULL CHECK(
                    action IN ('created','updated','revoked','legacy_snapshot')
                ),
                actor_user_id TEXT NOT NULL,
                old_content TEXT,
                new_content TEXT,
                source_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
                occurred_at TEXT NOT NULL,
                UNIQUE(memory_id,version)
            );
            CREATE INDEX IF NOT EXISTS idx_chat_memory_revisions_project
                ON chat_memory_revisions(project_id,memory_id,version DESC);
        """)
        # Old state had no revision ledger. Record only an accurate snapshot;
        # do not pretend to reconstruct previous edits or revocations.
        connection.execute(
            "INSERT INTO chat_memory_revisions "
            "(id,project_id,memory_id,version,action,actor_user_id,"
            "old_content,new_content,source_message_id,occurred_at) "
            "SELECT 'legacy-' || id,project_id,id,1,'legacy_snapshot',"
            "created_by_user_id,NULL,content,source_message_id,"
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
            "FROM chat_project_memories"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES (13, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
    # Keep the idempotency guard self-healing even if an operator restored a
    # database with the schema marker intact but the index missing.
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_client_message "
        "ON assistant_requests(conversation_id, client_message_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_user_updated_at "
        "ON conversations(user_id, updated_at DESC)"
    )
