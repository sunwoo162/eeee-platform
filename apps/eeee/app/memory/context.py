"""Bounded, privacy-aware memory context shared by all EEEE providers."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.memory.models import MemoryRecord
from app.memory.store import MemoryStore


_SECRET_PATTERN = re.compile(
    r"(?:api[_ -]?key|apikey|access[_ -]?token|refresh[_ -]?token|password|비밀번호|토큰|secret)\s*[:=]",
    re.IGNORECASE,
)


class MemoryContextPacket(BaseModel):
    """The only memory shape that may be handed to a model provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_ids: list[str] = Field(default_factory=list)
    preference_values: dict[str, str] = Field(default_factory=dict)
    prompt_context: str = "{}"


class MemoryContextCompiler:
    """Select relevant active memories without exporting the whole ledger."""

    def compile(
        self, query: str, store: MemoryStore, *, limit: int = 12
    ) -> MemoryContextPacket:
        if limit <= 0:
            return MemoryContextPacket()
        persistent_preferences = [
            record
            for record in store.search_user_preferences().values()
            if not _is_sensitive(record)
        ]
        relevant_records = [
            record for record in store.search(query, limit=limit)
            if not _is_sensitive(record)
        ]
        records = []
        for record in [*persistent_preferences, *relevant_records]:
            if record.id not in {item.id for item in records}:
                records.append(record)
            if len(records) >= limit:
                break
        preferences: dict[str, str] = {}
        for record in records:
            if record.kind != "user_preference":
                continue
            key = record.scope.get("preferenceKey")
            if isinstance(key, str) and key.strip():
                preferences[key] = record.content
        payload: dict[str, Any] = {
            "preferences": preferences,
            "memories": [
                {"id": record.id, "kind": record.kind, "content": record.content}
                for record in records
            ],
        }
        return MemoryContextPacket(
            memory_ids=[record.id for record in records],
            preference_values=preferences,
            prompt_context=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )


def _is_sensitive(record: MemoryRecord) -> bool:
    key = str(record.scope.get("preferenceKey", ""))
    value = f"{key} {record.content}"
    return bool(_SECRET_PATTERN.search(value)) or any(
        marker in value.casefold()
        for marker in ("sk-", "ghp_", "bearer ", "client_secret")
    )
