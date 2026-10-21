import sqlite3

from app.storage.sqlite import SQLiteStore


def test_existing_memory_conversation_turns_are_migrated_to_canonical_transcript(tmp_path):
    path = tmp_path / "state.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE conversation_turns ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, "
            "role TEXT NOT NULL, content TEXT NOT NULL, request_id TEXT, created_at TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO conversation_turns "
            "(conversation_id, role, content, request_id, created_at) VALUES (?, ?, ?, ?, ?)",
            [
                ("legacy-chat", "user", "첫 질문", "legacy-1", "2026-10-20T10:00:00+00:00"),
                ("legacy-chat", "assistant", "첫 답변", "legacy-1", "2026-10-20T10:00:01+00:00"),
            ],
        )

    store = SQLiteStore(path)
    store.init()

    from app.conversations.store import ConversationStore

    transcript = ConversationStore(store).get_transcript("legacy-chat")
    assert [(turn["role"], turn["content"], turn["requestId"]) for turn in transcript["turns"]] == [
        ("user", "첫 질문", "legacy-1"),
        ("assistant", "첫 답변", "legacy-1"),
    ]


def test_legacy_migration_does_not_duplicate_existing_canonical_turn(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = SQLiteStore(path)
    store.init()

    from app.conversations.store import ConversationStore

    conversations = ConversationStore(store)
    conversations.record_route_turn(
        "same-chat",
        user_content="기존 질문",
        assistant_content="기존 답변",
        request_id="same-1",
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO conversation_turns "
            "(conversation_id, role, content, request_id, created_at) VALUES (?, ?, ?, ?, ?)",
            ("same-chat", "user", "기존 질문", "same-1", "2026-10-20T10:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO conversation_turns "
            "(conversation_id, role, content, request_id, created_at) VALUES (?, ?, ?, ?, ?)",
            ("same-chat", "assistant", "기존 답변", "same-1", "2026-10-20T10:00:01+00:00"),
        )

    # A new schema version is applied only once, so exercise the migration
    # helper directly against a v2 marker to model an upgrade path.
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 3")
        connection.execute("DROP TABLE IF EXISTS _migration_probe")
    store.init()

    assert conversations.message_count("same-chat") == 2


def test_conversation_schema_has_user_scope_after_initialization(tmp_path):
    path = tmp_path / "state.sqlite3"

    store = SQLiteStore(path)
    store.init()

    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(conversations)").fetchall()
        }
        versions = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }

    assert "user_id" in columns
    assert 4 in versions
