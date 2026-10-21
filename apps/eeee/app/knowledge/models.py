from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class KnowledgeDocument:
    id: str
    title: str
    content: str
    scope: str
    content_hash: str
    created_at: datetime
    updated_at: datetime
    source_path: str | None = None
    snippet: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "scope": self.scope,
            "contentHash": self.content_hash,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }
        if self.source_path is not None:
            result["sourcePath"] = self.source_path
        if self.snippet is not None:
            result["snippet"] = self.snippet
        return result


@dataclass(frozen=True)
class KnowledgeResult:
    status: str
    message: str
    document: dict[str, Any] | None = None
    documents: list[dict[str, Any]] = field(default_factory=list)
    summary: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    error_code: str | None = None

