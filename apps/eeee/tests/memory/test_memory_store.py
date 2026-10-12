from pathlib import Path
from shutil import rmtree
from uuid import uuid4

import pytest

from app.memory.models import MemoryCandidate, MemoryStatus
from app.memory.store import MemoryConflictError, MemoryPromotionError, MemoryStore


def _candidate(
    candidate_id: str = "candidate-1",
    *,
    content: str = "Run responsive viewport checks",
    scope: dict[str, object] | None = None,
) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        kind="qa_rule",
        content=content,
        scope=scope or {"technology": "web"},
        source_project_id="project-1",
        source_artifact_ids=["qa-report-1"],
        evidence_ids=["evidence-1"],
        verification_ids=["claimlatch-report-1"],
        confidence=0.9,
        created_at="2026-10-06T00:00:00Z",
    )


@pytest.fixture
def memory_store() -> tuple[MemoryStore, Path]:
    path = Path("var") / ("memory-test-" + uuid4().hex) / "memory.sqlite3"
    store = MemoryStore(path)
    store.init()
    yield store, path
    rmtree(path.parent, ignore_errors=True)


def test_candidate_survives_store_reopen(memory_store: tuple[MemoryStore, Path]) -> None:
    store, path = memory_store
    saved = store.save_candidate(_candidate())

    reopened = MemoryStore(path)
    reopened.init()
    loaded = reopened.get(saved.id)

    assert loaded.status is MemoryStatus.CANDIDATE
    assert loaded.content == "Run responsive viewport checks"
    assert loaded.source_project_id == "project-1"


def test_user_preference_is_persistent_and_latest_value_replaces_previous(memory_store):
    store, _path = memory_store

    first = store.save_user_preference("language", "한국어")
    second = store.save_user_preference("language", "English")

    assert first.status is MemoryStatus.ACTIVE
    assert second.status is MemoryStatus.ACTIVE
    assert store.get(first.id).status is MemoryStatus.SUPERSEDED
    assert store.search_user_preferences()["language"].content == "English"


def test_candidate_requires_evidence_to_become_active(memory_store: tuple[MemoryStore, Path]) -> None:
    store, _ = memory_store
    saved = store.save_candidate(_candidate())

    active = store.promote(saved.id, actor="user", evidence_ids=["evidence-1"])

    assert active.status is MemoryStatus.ACTIVE
    assert active.approved_by == "user"
    assert active.last_verified_at is not None


def test_candidate_cannot_be_overwritten_with_different_content(
    memory_store: tuple[MemoryStore, Path],
) -> None:
    store, _ = memory_store
    store.save_candidate(_candidate())

    with pytest.raises(MemoryConflictError):
        store.save_candidate(_candidate(content="Different rule"))


def test_active_memory_can_be_revoked_and_superseded(
    memory_store: tuple[MemoryStore, Path],
) -> None:
    store, _ = memory_store
    original = store.save_candidate(_candidate())
    store.promote(original.id, actor="user", evidence_ids=["evidence-1"])
    replacement = store.save_candidate(_candidate("candidate-2", content="Run 320/375/768px checks"))
    store.promote(replacement.id, actor="user", evidence_ids=["evidence-2"])

    superseded = store.supersede(original.id, replacement.id)
    revoked = store.revoke(replacement.id, reason="User rejected the new rule")

    assert superseded.status is MemoryStatus.SUPERSEDED
    assert revoked.status is MemoryStatus.REVOKED


def test_memory_records_can_be_inspected_by_lifecycle_status(memory_store):
    store, _ = memory_store
    candidate = store.save_candidate(_candidate())
    store.promote(candidate.id, actor="user", evidence_ids=["evidence-1"])

    assert [item.id for item in store.list_records(status=MemoryStatus.ACTIVE)] == [candidate.id]
    assert [item.id for item in store.list_records(status=MemoryStatus.CANDIDATE)] == []
    assert store.list_records(source_project_id="project-1")[0].id == candidate.id


def test_user_can_delete_editable_memory_without_deleting_its_audit_event(memory_store):
    store, _ = memory_store
    candidate = store.save_candidate(_candidate())
    deleted = store.delete(candidate.id, actor="user", reason="No longer useful")

    assert deleted.id == candidate.id
    with pytest.raises(KeyError):
        store.get(candidate.id)
    with store._connect() as connection:
        event = connection.execute(
            "SELECT event_type, actor FROM memory_events WHERE memory_id = ? ORDER BY id DESC LIMIT 1",
            (candidate.id,),
        ).fetchone()
    assert tuple(event) == ("deleted", "user")


def test_delete_refuses_superseded_memory_to_preserve_replacement_history(memory_store):
    store, _ = memory_store
    original = store.save_candidate(_candidate())
    store.promote(original.id, actor="user", evidence_ids=["evidence-1"])
    replacement = store.save_candidate(_candidate("candidate-2", content="New rule"))
    store.promote(replacement.id, actor="user", evidence_ids=["evidence-2"])
    store.supersede(original.id, replacement.id)

    with pytest.raises(MemoryPromotionError, match="superseded"):
        store.delete(original.id, actor="user", reason="remove old record")
