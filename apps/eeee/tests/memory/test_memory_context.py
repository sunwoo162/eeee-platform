from datetime import datetime, timezone

from app.memory.context import MemoryContextCompiler
from app.memory.models import MemoryCandidate
from app.memory.store import MemoryStore


def _memory(path, memory_id: str, content: str, *, kind="user_preference", scope=None):
    store = MemoryStore(path)
    store.init()
    record = store.save_candidate(MemoryCandidate(
        candidate_id=memory_id,
        kind=kind,
        content=content,
        scope=scope or {"preferenceKey": memory_id},
        source_project_id="user",
        source_artifact_ids=[f"artifact-{memory_id}"],
        evidence_ids=[f"evidence-{memory_id}"],
        verification_ids=[f"verification-{memory_id}"],
        confidence=0.95,
        created_at=datetime.now(timezone.utc),
    ))
    store.promote(record.id, actor="user", evidence_ids=record.evidence_ids)
    return store


def test_compiler_includes_relevant_active_memory_and_preferences(tmp_path):
    path = tmp_path / "memory.sqlite3"
    store = _memory(path, "language", "한국어로 답변", scope={"preferenceKey": "language"})
    packet = MemoryContextCompiler().compile("답변 언어", store)

    assert packet.preference_values == {"language": "한국어로 답변"}
    assert packet.memory_ids == ["language"]
    assert "한국어로 답변" in packet.prompt_context


def test_compiler_excludes_secret_like_values(tmp_path):
    path = tmp_path / "memory.sqlite3"
    store = _memory(path, "token", "API key: super-secret", scope={"preferenceKey": "token"})
    packet = MemoryContextCompiler().compile("token", store)

    assert packet.preference_values == {}
    assert packet.memory_ids == []
    assert "super-secret" not in packet.prompt_context


def test_compiler_bounds_context_size(tmp_path):
    path = tmp_path / "memory.sqlite3"
    store = _memory(path, "language", "한국어")
    packet = MemoryContextCompiler().compile("", store, limit=0)

    assert packet.memory_ids == []
    assert packet.preference_values == {}
