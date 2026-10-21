from __future__ import annotations

from pathlib import Path

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

