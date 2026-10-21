from __future__ import annotations

import re

from app.knowledge.models import KnowledgeResult
from app.knowledge.store import KnowledgeStore


_SAVE = re.compile(r"^(?:문서\s*)?저장(?:해줘|해|하기)?\s*[:：]\s*(.+)$", re.IGNORECASE | re.DOTALL)
_SEARCH = re.compile(r"^(?:문서\s*)?(?:검색|찾아|조회|보여)(?:줘|보기|해줘)?\s*[:：]?\s*(.*)$", re.IGNORECASE | re.DOTALL)
_SUMMARY = re.compile(r"^(?:문서\s*)?요약(?:해줘|해|하기)?\s*[:：]?\s*(.*)$", re.IGNORECASE | re.DOTALL)


class KnowledgeService:
    """Interpret only explicit, bounded local document commands."""

    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def handle(self, text: str, *, scope: str = "global") -> KnowledgeResult:
        text = text.strip()
        save = _SAVE.match(text)
        if save:
            return self._save(save.group(1), scope=scope)
        summary = _SUMMARY.match(text)
        if summary:
            return self._summarize(summary.group(1), scope=scope)
        search = _SEARCH.match(text)
        if search:
            return self._search(search.group(1), scope=scope)
        return KnowledgeResult(
            status="blocked",
            error_code="knowledge_request_ambiguous",
            message="저장·검색·요약 중 어떤 문서 작업인지와 대상 내용을 알려줘.",
        )

    def _save(self, payload: str, *, scope: str) -> KnowledgeResult:
        lines = [line.strip() for line in payload.splitlines() if line.strip()]
        if len(lines) < 2:
            return KnowledgeResult(
                status="blocked", error_code="knowledge_document_content_required",
                message="문서 제목 다음 줄에 저장할 내용을 적어줘.",
            )
        document = self.store.save_text(lines[0], "\n".join(lines[1:]), scope=scope)
        return KnowledgeResult(
            status="completed", document=document.as_dict(),
            message=f"{document.title} 문서를 저장했어.",
        )

    def _search(self, query: str, *, scope: str) -> KnowledgeResult:
        documents = self.store.search(query, scope=scope)
        if not documents:
            return KnowledgeResult(status="completed", message="조건에 맞는 문서를 찾지 못했어.")
        serialized = [document.as_dict() for document in documents]
        return KnowledgeResult(
            status="completed", documents=serialized,
            sources=[_source(document) for document in documents],
            message="\n".join(f"- {document.title}: {document.snippet or ''}" for document in documents),
        )

    def _summarize(self, query: str, *, scope: str) -> KnowledgeResult:
        if not query.strip():
            return KnowledgeResult(
                status="blocked",
                error_code="knowledge_summary_target_required",
                message="어떤 문서를 요약할지 제목이나 검색어를 알려줘.",
            )
        documents = self.store.search(query, scope=scope)
        if not documents:
            return KnowledgeResult(status="completed", message="요약할 문서를 찾지 못했어.")
        document = documents[0]
        sentences = re.split(r"(?<=[.!?。！？])\s+|\n+", document.content)
        selected = [sentence.strip() for sentence in sentences if sentence.strip()][:3]
        summary = " ".join(selected)[:600]
        source = _source(document)
        return KnowledgeResult(
            status="completed", summary=summary, sources=[source],
            message=f"{document.title} 요약:\n{summary}\n\n출처: {document.title} ({document.content_hash[:12]})",
        )


def _source(document) -> dict[str, str]:
    return {
        "documentId": document.id,
        "title": document.title,
        "contentHash": document.content_hash,
        "snippet": document.snippet or document.content[:240],
    }

