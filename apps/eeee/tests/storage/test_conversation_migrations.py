import sqlite3

from app.storage.sqlite import SQLiteStore


def test_conversation_migration_is_applied_without_removing_legacy_tables(tmp_path) -> None:
    database = tmp_path / "state.sqlite3"
    store = SQLiteStore(database)

    store.init()
    store.init()

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert {"projects", "requests", "memory_records", "conversations", "messages"} <= tables
    assert {"assistant_requests", "assistant_events"} <= tables
    assert versions == [(1,)]


def test_migration_preserves_an_existing_project(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    store.create_project("project-1", "Existing", str(tmp_path / "workspace"), revision="r1")

    store.init()

    assert store.get_project("project-1").revision == "r1"
