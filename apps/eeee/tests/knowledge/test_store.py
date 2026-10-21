from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3

from app.knowledge.store import KnowledgeStore


def test_knowledge_store_persists_documents_and_searches_bounded_snippets(tmp_path: Path) -> None:
    database = tmp_path / "eeee.sqlite3"
    store = KnowledgeStore(database)

    saved = store.save_text(
        "식단 계획",
        "월요일 아침은 오트밀이다. 점심은 비빔밥이다.",
        scope="desktop-default",
    )

    restored = KnowledgeStore(database)
    found = restored.search("비빔밥", scope="desktop-default")

    assert saved.id.startswith("document-")
    assert found[0].id == saved.id
    assert found[0].title == "식단 계획"
    assert "비빔밥" in found[0].snippet
    assert found[0].content_hash


def test_knowledge_store_deduplicates_same_content_in_scope(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "eeee.sqlite3")

    first = store.save_text("회의록", "결정: 금요일 배포", scope="desktop-default")
    second = store.save_text("다른 제목", "결정: 금요일 배포", scope="desktop-default")

    assert second.id == first.id
    assert len(store.list(scope="desktop-default")) == 1


def test_knowledge_store_does_not_cross_scope(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "eeee.sqlite3")
    store.save_text("개인 문서", "개인 내용", scope="private")

    assert store.search("개인", scope="desktop-default") == []


def test_knowledge_store_does_not_cross_user_scope(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "eeee.sqlite3")
    store.save_text("A 문서", "A 전용 내용", scope="same-chat", user_id="user-a")

    assert store.search("내용", scope="same-chat", user_id="user-a")
    assert store.search("내용", scope="same-chat", user_id="user-b") == []


def test_knowledge_store_migrates_legacy_documents_to_local_user(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE local_documents (
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
            INSERT INTO local_documents
                (id, title, content, scope, content_hash, created_at, updated_at)
            VALUES ('legacy-1', '기존 문서', '기존 내용', 'desktop-default', 'hash-1',
                    '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
            """
        )

    store = KnowledgeStore(database)

    assert [item.id for item in store.search("기존", scope="desktop-default")] == ["legacy-1"]
    assert store.search("기존", scope="desktop-default", user_id="user-b") == []


def test_knowledge_store_concurrent_same_document_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "eeee.sqlite3"

    def save(_index: int):
        return KnowledgeStore(database).save_text(
            "동시 문서", "동일 내용", scope="desktop-default"
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(save, range(8)))

    assert {item.id for item in results} == {results[0].id}
    assert len(KnowledgeStore(database).list(scope="desktop-default")) == 1


def test_knowledge_store_can_restore_deleted_content_without_unique_conflict(tmp_path: Path) -> None:
    database = tmp_path / "eeee.sqlite3"
    store = KnowledgeStore(database)
    first = store.save_text("초안", "다시 저장할 내용", scope="desktop-default")
    with store._session() as connection:
        connection.execute(
            "UPDATE local_documents SET deleted_at = '2026-01-01T00:00:00+00:00' WHERE id = ?",
            (first.id,),
        )

    restored = store.save_text("최종본", "다시 저장할 내용", scope="desktop-default")

    assert restored.id == first.id
    assert restored.title == "최종본"
    assert [item.id for item in store.list(scope="desktop-default")] == [first.id]

