from __future__ import annotations

from pathlib import Path

from app.knowledge.service import KnowledgeService
from app.knowledge.store import KnowledgeStore


def test_knowledge_service_saves_and_searches_natural_language_requests(tmp_path: Path) -> None:
    service = KnowledgeService(KnowledgeStore(tmp_path / "eeee.sqlite3"))

    saved = service.handle("문서 저장해줘: 식단 계획\n월요일은 오트밀, 점심은 비빔밥", scope="desktop-default")
    found = service.handle("문서 검색해줘: 비빔밥", scope="desktop-default")

    assert saved.status == "completed"
    assert saved.document is not None
    assert found.status == "completed"
    assert found.documents[0]["title"] == "식단 계획"


def test_knowledge_service_summary_keeps_sources_and_is_bounded(tmp_path: Path) -> None:
    service = KnowledgeService(KnowledgeStore(tmp_path / "eeee.sqlite3"))
    service.handle(
        "문서 저장해줘: 프로젝트 메모\n요구사항을 먼저 확정한다. 테스트를 작성한다. 배포 전에 검증한다.",
        scope="desktop-default",
    )

    result = service.handle("문서 요약해줘: 프로젝트", scope="desktop-default")

    assert result.status == "completed"
    assert result.summary
    assert result.sources
    assert result.sources[0]["contentHash"]
    assert "프로젝트 메모" in result.message


def test_knowledge_service_blocks_ambiguous_document_request(tmp_path: Path) -> None:
    service = KnowledgeService(KnowledgeStore(tmp_path / "eeee.sqlite3"))

    result = service.handle("문서 정리해줘", scope="desktop-default")

    assert result.status == "blocked"
    assert result.error_code == "knowledge_request_ambiguous"


def test_knowledge_service_requires_a_search_target_for_summary(tmp_path: Path) -> None:
    service = KnowledgeService(KnowledgeStore(tmp_path / "eeee.sqlite3"))
    service.handle("문서 저장해줘: 첫 문서\n임의의 문서 내용", scope="desktop-default")

    result = service.handle("문서 요약해줘", scope="desktop-default")

    assert result.status == "blocked"
    assert result.error_code == "knowledge_summary_target_required"

