import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, BrokenBarrierError, Event

import pytest

from app.domain.models import CandidateScore, Decision, RepositorySnapshot, RequestBrief
from app.storage.sqlite import SQLiteStore
from app.workflow.approvals import ApprovalError, AlreadyApprovedError, ApprovalService, CandidateSetChangedError


def test_store_connection_context_closes_connection(tmp_path):
    store = SQLiteStore(tmp_path / "context.sqlite3")
    store.init()

    connection = store._connect()
    with connection:
        connection.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def candidate(full_name: str, *, license_spdx: str | None) -> CandidateScore:
    return CandidateScore(
        repository=RepositorySnapshot(
            full_name=full_name,
            html_url=f"https://example.com/{full_name}",
            description=f"Description for {full_name}",
            stars=12,
            forks=3,
            open_issues=2,
            license_spdx=license_spdx,
            default_branch="main",
            pushed_at="2026-09-28T00:00:00Z",
            topics=["python", "tooling"],
        ),
        total=0.8,
        dimension_scores={"fit": 0.9, "activity": 0.7},
        evidence=[f"Evidence for {full_name}"],
        risks=[f"Risk for {full_name}"],
        status="candidate",
    )


def test_store_round_trips_candidates_decision_and_ordered_events(tmp_path):
    store = SQLiteStore(tmp_path / "store.sqlite3")
    store.init()
    store.init()
    brief = RequestBrief(
        raw_text="Find a useful project",
        goal="Find a useful project",
        target_type="library",
        constraints=["Python"],
        acceptance_criteria=["Active"],
    )
    request_id = store.save_request(brief)
    expected = [candidate("owner/one", license_spdx=None), candidate("owner/two", license_spdx="MIT")]

    store.save_candidates(request_id, expected)

    actual = store.get_candidates(request_id)
    assert actual == expected
    assert actual[0].repository.license_spdx is None
    assert actual[1].evidence == expected[1].evidence
    assert actual[1].risks == expected[1].risks

    store.save_decision(
        Decision(
            request_id=request_id,
            selected=["owner/one"],
            alternatives=["owner/two"],
            approved=False,
            notes="Selected first",
        )
    )
    run = store.create_run(request_id, str(tmp_path / "workspace"))
    events = [{"type": "started", "sequence": 1}, {"type": "finished", "sequence": 2}]
    for event in events:
        store.append_event(run.id, event)

    assert store.get_run(run.id).events == events


def test_run_creation_time_is_persisted_and_exposed_in_history(tmp_path):
    store = SQLiteStore(tmp_path / "run-time.sqlite3")
    store.init()

    run = store.create_run("request", str(tmp_path / "workspace"))

    assert run.created_at is not None
    datetime.fromisoformat(run.created_at)
    assert store.get_run(run.id).created_at == run.created_at
    assert store.list_runs()[0].created_at == run.created_at


def test_init_migrates_legacy_runs_without_losing_them(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE runs (id TEXT PRIMARY KEY, request_id TEXT NOT NULL, status TEXT NOT NULL, "
            "workspace TEXT NOT NULL, artifacts_json TEXT NOT NULL, error TEXT)"
        )
        connection.execute(
            "INSERT INTO runs VALUES ('legacy', 'request', 'completed', '/workspace', '[]', NULL)"
        )
        connection.execute(
            "CREATE TABLE run_events (run_id TEXT NOT NULL, position INTEGER NOT NULL, event_json TEXT NOT NULL, "
            "PRIMARY KEY (run_id, position))"
        )

    store = SQLiteStore(database)
    store.init()

    legacy = store.get_run("legacy")
    assert legacy.status == "completed"
    assert legacy.created_at is None


def test_list_runs_applies_limit_and_offset_in_stable_order(tmp_path):
    store = SQLiteStore(tmp_path / "pages.sqlite3")
    store.init()
    runs = [store.create_run("request", str(tmp_path / f"workspace-{n}")) for n in range(3)]

    assert [run.id for run in store.list_runs(limit=2, offset=0)] == [runs[2].id, runs[1].id]
    assert [run.id for run in store.list_runs(limit=2, offset=2)] == [runs[0].id]
    assert [run.id for run in store.list_runs()] == [run.id for run in runs]


def test_list_runs_supports_explicit_sort_direction(tmp_path):
    store = SQLiteStore(tmp_path / "sorted-pages.sqlite3")
    store.init()
    runs = [store.create_run("request", str(tmp_path / f"workspace-{n}")) for n in range(3)]

    assert [run.id for run in store.list_runs(sort="newest")] == [run.id for run in reversed(runs)]
    assert [run.id for run in store.list_runs(sort="oldest")] == [run.id for run in runs]
    oldest_page, total = store.list_runs_with_count(sort="oldest", limit=2)

    assert [run.id for run in oldest_page] == [runs[0].id, runs[1].id]
    assert total == 3
    with pytest.raises(ValueError, match="sort must be newest or oldest"):
        store.list_runs(sort="random")


def test_list_runs_sorts_timestamps_by_instant_across_timezones(tmp_path):
    store = SQLiteStore(tmp_path / "timezone-sorted-runs.sqlite3")
    store.init()
    later = store.create_run("request", str(tmp_path / "workspace-later"))
    earlier = store.create_run("request", str(tmp_path / "workspace-earlier"))
    with store._connect() as connection:
        connection.execute(
            "UPDATE runs SET created_at = ? WHERE id = ?",
            ("2025-01-01T00:30:00+01:00", earlier.id),
        )
        connection.execute(
            "UPDATE runs SET created_at = ? WHERE id = ?",
            ("2025-01-01T00:00:00Z", later.id),
        )

    assert [run.id for run in store.list_runs(sort="newest")] == [later.id, earlier.id]
    assert [run.id for run in store.list_runs(sort="oldest")] == [earlier.id, later.id]


def test_list_runs_filters_timestamps_by_instant_across_timezones(tmp_path):
    store = SQLiteStore(tmp_path / "timezone-filtered-runs.sqlite3")
    store.init()
    earlier = store.create_run("request", str(tmp_path / "workspace-earlier"))
    later = store.create_run("request", str(tmp_path / "workspace-later"))
    with store._connect() as connection:
        connection.execute(
            "UPDATE runs SET created_at = ? WHERE id = ?",
            ("2025-01-01T00:30:00+01:00", earlier.id),
        )
        connection.execute(
            "UPDATE runs SET created_at = ? WHERE id = ?",
            ("2025-01-01T00:00:00Z", later.id),
        )

    assert [run.id for run in store.list_runs(created_after="2025-01-01T00:00:00Z")] == [later.id]
    assert [run.id for run in store.list_runs(created_before="2025-01-01T00:30:00+01:00")] == [earlier.id]


def test_list_runs_preserves_microsecond_precision_for_sorting_and_filters(tmp_path):
    store = SQLiteStore(tmp_path / "precise-timestamps.sqlite3")
    store.init()
    later = store.create_run("request", str(tmp_path / "workspace-later"))
    earlier = store.create_run("request", str(tmp_path / "workspace-earlier"))
    with store._connect() as connection:
        connection.execute(
            "UPDATE runs SET created_at = ? WHERE id = ?",
            ("2025-01-01T00:00:00.000100+00:00", earlier.id),
        )
        connection.execute(
            "UPDATE runs SET created_at = ? WHERE id = ?",
            ("2025-01-01T00:00:00.000400+00:00", later.id),
        )

    assert [run.id for run in store.list_runs(sort="newest")] == [later.id, earlier.id]
    assert [run.id for run in store.list_runs(sort="oldest")] == [earlier.id, later.id]
    assert [
        run.id for run in store.list_runs(created_after="2025-01-01T00:00:00.000250Z")
    ] == [later.id]
    assert [
        run.id for run in store.list_runs(created_before="2025-01-01T00:00:00.000250Z")
    ] == [earlier.id]


def test_list_runs_filters_status_and_id_or_request_id_search(tmp_path):
    store = SQLiteStore(tmp_path / "filtered-pages.sqlite3")
    store.init()
    first = store.create_run("request-alpha", str(tmp_path / "workspace-1"))
    second = store.create_run("request-beta", str(tmp_path / "workspace-2"))
    third = store.create_run("request-alpha", str(tmp_path / "workspace-3"))
    store.update_run(second.id, status="failed", artifacts=[], error="failed")

    assert [run.id for run in store.list_runs(status="created")] == [first.id, third.id]
    assert [run.id for run in store.list_runs(search="ALPHA")] == [first.id, third.id]
    assert [run.id for run in store.list_runs(search=second.id[:8].upper())] == [second.id]
    assert [run.id for run in store.list_runs(status="created", search="ALPHA", limit=1)] == [third.id]
    assert [run.id for run in store.list_runs(status="created", search="ALPHA", limit=1, offset=1)] == [first.id]


def test_list_runs_loads_a_page_with_one_database_connection(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "batch-list.sqlite3")
    store.init()
    runs = [store.create_run("request", str(tmp_path / f"workspace-{n}")) for n in range(3)]
    for run in runs:
        store.append_event(run.id, {"type": "started", "run_id": run.id})

    original_connect = store._connect
    connection_count = 0

    def counted_connect():
        nonlocal connection_count
        connection_count += 1
        return original_connect()

    monkeypatch.setattr(store, "_connect", counted_connect)

    page = store.list_runs(limit=2)

    assert connection_count == 1
    assert [run.id for run in page] == [runs[2].id, runs[1].id]
    assert [run.events[0]["run_id"] for run in page] == [runs[2].id, runs[1].id]


def test_init_creates_indexes_for_run_history_filters(tmp_path):
    store = SQLiteStore(tmp_path / "indexed-runs.sqlite3")
    store.init()

    with sqlite3.connect(store.path) as connection:
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(runs)").fetchall()
        }

    assert "idx_runs_request_id" in indexes
    assert "idx_runs_status" in indexes
    assert "idx_runs_created_at" in indexes


def test_count_runs_uses_the_same_filters_as_history_listing(tmp_path):
    store = SQLiteStore(tmp_path / "counted-runs.sqlite3")
    store.init()
    store.create_run("request-alpha", str(tmp_path / "workspace-1"))
    failed = store.create_run("request-beta", str(tmp_path / "workspace-2"))
    store.update_run(failed.id, status="failed", artifacts=[], error="failed")
    store.create_run("request-alpha", str(tmp_path / "workspace-3"))

    assert store.count_runs() == 3
    assert store.count_runs(status="created") == 2
    assert store.count_runs(search="BETA") == 1


def test_list_runs_filters_by_creation_time_and_counts_matching_rows(tmp_path):
    store = SQLiteStore(tmp_path / "timed-runs.sqlite3")
    store.init()
    runs = [store.create_run("request", str(tmp_path / f"workspace-{n}")) for n in range(3)]
    timestamps = [
        "2026-09-28T00:00:00+00:00",
        "2026-09-29T00:00:00+00:00",
        "2026-09-30T00:00:00+00:00",
    ]
    with store._connect() as connection:
        for run, created_at in zip(runs, timestamps):
            connection.execute("UPDATE runs SET created_at = ? WHERE id = ?", (created_at, run.id))

    page, total = store.list_runs_with_count(
        created_after=timestamps[1], created_before=timestamps[2], limit=1
    )

    assert [run.id for run in page] == [runs[2].id]
    assert total == 2
    assert [run.id for run in store.list_runs(created_before=timestamps[0])] == [runs[0].id]


def test_list_runs_with_count_returns_filtered_page_and_total(tmp_path):
    store = SQLiteStore(tmp_path / "consistent-runs.sqlite3")
    store.init()
    first = store.create_run("request-alpha", str(tmp_path / "workspace-1"))
    failed = store.create_run("request-beta", str(tmp_path / "workspace-2"))
    store.update_run(failed.id, status="failed", artifacts=[], error="failed")
    third = store.create_run("request-alpha", str(tmp_path / "workspace-3"))

    page, total = store.list_runs_with_count(
        "request-alpha", status="created", search="ALPHA", limit=1
    )
    empty_page, empty_total = store.list_runs_with_count(search="missing", limit=1)

    assert [run.id for run in page] == [third.id]
    assert total == 2
    assert empty_page == []
    assert empty_total == 0
    assert first.id != third.id


def test_save_decision_rejects_direct_approval_without_audit_event(tmp_path):
    store = SQLiteStore(tmp_path / "decision.sqlite3")
    store.init()
    approved = Decision(
        request_id="request-1", selected=["org/one"], alternatives=["org/two"],
        approved=True, notes="original",
    )

    with pytest.raises(ApprovalError, match="approval"):
        store.save_decision(approved)

    assert store.get_decision("request-1") is None
    assert store.get_decision_events("request-1") == []


def test_save_decision_refuses_to_overwrite_approved_decision(tmp_path):
    store = SQLiteStore(tmp_path / "decision.sqlite3")
    store.init()
    store.save_candidates("request-1", [
        candidate("org/one", license_spdx="MIT"), candidate("org/two", license_spdx="MIT"),
    ])
    approved = ApprovalService(store).approve_decision("request-1", ["org/one"])

    with pytest.raises(AlreadyApprovedError, match="already approved"):
        store.save_decision(approved.model_copy(update={"approved": False, "notes": "revised"}))

    assert store.get_decision("request-1") == approved
    assert store.get_decision_events("request-1") == [
        {"action": "approved", "selected": ["org/one"]}
    ]


def test_save_candidates_refuses_replacement_after_approval(tmp_path):
    store = SQLiteStore(tmp_path / "candidates.sqlite3")
    store.init()
    original = [candidate("org/one", license_spdx="MIT"), candidate("org/two", license_spdx="MIT")]
    store.save_candidates("request-1", original)
    ApprovalService(store).approve_decision("request-1", ["org/one"])

    with pytest.raises(AlreadyApprovedError, match="already approved"):
        store.save_candidates("request-1", [candidate("org/three", license_spdx="MIT")])

    assert store.get_candidates("request-1") == original


def test_save_approval_once_rejects_candidate_snapshot_mismatch(tmp_path):
    store = SQLiteStore(tmp_path / "snapshot.sqlite3")
    store.init()
    store.save_candidates("request-1", [
        candidate("org/one", license_spdx="MIT"), candidate("org/three", license_spdx="MIT"),
    ])
    decision = Decision(
        request_id="request-1", selected=["org/one"], alternatives=["org/two"],
        approved=True, notes="",
    )

    with pytest.raises(CandidateSetChangedError, match="candidate set changed"):
        store.save_approval_once(decision, {"action": "approved"}, [
            candidate("org/one", license_spdx="MIT"), candidate("org/two", license_spdx="MIT"),
        ])

    assert store.get_decision("request-1") is None
    assert store.get_decision_events("request-1") == []


def test_concurrent_event_appends_keep_every_event(tmp_path, monkeypatch):
    database_path = tmp_path / "concurrent.sqlite3"
    store = SQLiteStore(database_path)
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    readers = Barrier(2, timeout=2)
    starters = Barrier(2, timeout=5)

    class CoordinatedCursor(sqlite3.Cursor):
        def fetchone(self):
            row = super().fetchone()
            try:
                readers.wait()
            except BrokenBarrierError:
                # A write transaction keeps the second reader out until this one commits.
                pass
            return row

    class CoordinatedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if "MAX(position)" in sql:
                return self.cursor(factory=CoordinatedCursor).execute(sql, parameters)
            return super().execute(sql, parameters)

        def __exit__(self, exc_type, exc_value, traceback):
            try:
                return super().__exit__(exc_type, exc_value, traceback)
            finally:
                self.close()

    def connect(_store):
        connection = sqlite3.connect(database_path, factory=CoordinatedConnection)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(SQLiteStore, "_connect", connect)
    events = [{"type": "worker", "id": worker_id} for worker_id in range(2)]

    def append(event):
        starters.wait()
        SQLiteStore(database_path).append_event(run.id, event)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(append, event) for event in events]
        for future in futures:
            future.result(timeout=10)

    actual = store.get_run(run.id).events
    assert len(actual) == len(events)
    assert {event["id"] for event in actual} == {event["id"] for event in events}


LEASE_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


class AdjustableLeaseClock:
    def __init__(self, now: datetime):
        self.now = now
        self.sampled = Event()

    def __call__(self) -> datetime:
        self.sampled.set()
        return self.now


class BeginTrackedConnection:
    def __init__(self, connection: sqlite3.Connection, begin_attempted: Event):
        self.connection = connection
        self.begin_attempted = begin_attempted

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, *args):
        return self.connection.__exit__(*args)

    def execute(self, statement, *args):
        if statement == "BEGIN IMMEDIATE":
            self.begin_attempted.set()
        return self.connection.execute(statement, *args)

    def __getattr__(self, name):
        return getattr(self.connection, name)


def run_after_writer_lock(store: SQLiteStore, clock: AdjustableLeaseClock, action):
    original_connect = store._connect
    begin_attempted = Event()
    store._connect = lambda: BeginTrackedConnection(original_connect(), begin_attempted)
    try:
        with sqlite3.connect(store.path) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(action)
                try:
                    assert begin_attempted.wait(timeout=2)
                    assert not clock.sampled.is_set(), "clock sampled before writer lock"
                    clock.now = LEASE_NOW + timedelta(seconds=61)
                finally:
                    writer.rollback()
                return future.result(timeout=5)
    finally:
        store._connect = original_connect


def test_execution_claim_samples_clock_after_writer_lock(tmp_path):
    store = SQLiteStore(tmp_path / "claim-clock.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    clock = AdjustableLeaseClock(LEASE_NOW)

    claim = run_after_writer_lock(
        store, clock, lambda: store.claim_run_execution(run.id, "owner", clock)
    )

    assert claim.acquired is True
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT expires_at FROM run_execution_leases WHERE run_id = ?", (run.id,)
        ).fetchone()[0] == "2026-10-01T12:02:01+00:00"


def test_execution_claim_creates_one_lease_row_and_persists_running_run(tmp_path):
    store = SQLiteStore(tmp_path / "lease.sqlite3")
    store.init()
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))

    claim = store.claim_run_execution(run.id, "owner-one", LEASE_NOW)

    assert claim.acquired is True
    assert claim.reason == "acquired"
    assert claim.generation == 1
    assert claim.run == store.get_run(run.id)
    assert claim.run.status == "running"
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA table_info(run_execution_leases)").fetchall()
        assert connection.execute("SELECT * FROM run_execution_leases").fetchall() == [
            (run.id, "owner-one", 1, "2026-10-01T12:01:00+00:00")
        ]


def test_execution_claim_returns_persisted_run_for_live_competing_owner(tmp_path):
    store = SQLiteStore(tmp_path / "lease.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    first = store.claim_run_execution(run.id, "owner-one", LEASE_NOW)

    second = store.claim_run_execution(run.id, "owner-two", LEASE_NOW + timedelta(seconds=10))

    assert second.acquired is False
    assert second.reason == "already_running"
    assert second.generation == first.generation
    assert second.run == store.get_run(run.id)
    assert second.run.status == "running"
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT owner_token, generation FROM run_execution_leases WHERE run_id = ?", (run.id,)
        ).fetchone() == ("owner-one", 1)


def test_execution_claim_expires_without_reclaiming_and_warns_about_workspace(tmp_path):
    store = SQLiteStore(tmp_path / "lease.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    first = store.claim_run_execution(run.id, "owner-one", LEASE_NOW)

    expired = store.claim_run_execution(run.id, "owner-two", LEASE_NOW + timedelta(seconds=61))

    assert expired.acquired is False
    assert expired.reason == "expired"
    assert expired.generation > first.generation
    assert expired.run.status == "failed"
    assert expired.run == store.get_run(run.id)
    assert "workspace" in expired.run.error.lower()
    assert "partial" in expired.run.error.lower()
    assert "retry" in expired.run.error.lower()
    assert expired.run.events[-1]["type"] == "execution_expired"
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT owner_token, generation, expires_at FROM run_execution_leases WHERE run_id = ?",
            (run.id,),
        ).fetchone() == (None, expired.generation, None)
    assert store.renew_run_execution(run.id, "owner-one", first.generation, LEASE_NOW) is False


def test_execution_claim_expires_at_exact_lease_boundary(tmp_path):
    store = SQLiteStore(tmp_path / "lease-boundary.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    store.claim_run_execution(run.id, "owner-one", LEASE_NOW)

    claim = store.claim_run_execution(run.id, "owner-two", LEASE_NOW + timedelta(seconds=60))

    assert claim.acquired is False
    assert claim.reason == "expired"
    assert claim.run.status == "failed"


def test_execution_claim_fails_legacy_running_run_without_lease(tmp_path):
    store = SQLiteStore(tmp_path / "legacy-lease.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    store.update_run(run.id, status="running", artifacts=[], error=None)

    stale = store.claim_run_execution(run.id, "owner", LEASE_NOW)

    assert stale.acquired is False
    assert stale.reason == "expired"
    assert stale.run.status == "failed"
    assert "partial" in stale.run.error.lower()
    assert stale.run.events[-1]["type"] == "execution_stale"
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT owner_token, generation, expires_at FROM run_execution_leases WHERE run_id = ?",
            (run.id,),
        ).fetchone() == (None, stale.generation, None)


def test_execution_lease_renewal_requires_live_matching_owner_and_generation(tmp_path):
    store = SQLiteStore(tmp_path / "renew.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    claim = store.claim_run_execution(run.id, "owner", LEASE_NOW)

    assert store.renew_run_execution(run.id, "other", claim.generation, LEASE_NOW) is False
    assert store.renew_run_execution(run.id, "owner", claim.generation + 1, LEASE_NOW) is False
    assert store.renew_run_execution(run.id, "owner", claim.generation, LEASE_NOW + timedelta(seconds=30)) is True
    assert store.renew_run_execution(run.id, "owner", claim.generation, LEASE_NOW + timedelta(seconds=91)) is False
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT expires_at FROM run_execution_leases WHERE run_id = ?", (run.id,)
        ).fetchone()[0] == "2026-10-01T12:01:30+00:00"


def test_execution_lease_renewal_never_shortens_expiry_after_backward_clock(tmp_path):
    store = SQLiteStore(tmp_path / "backward-clock.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    claim = store.claim_run_execution(run.id, "owner", LEASE_NOW)
    assert store.renew_run_execution(
        run.id, "owner", claim.generation, LEASE_NOW + timedelta(seconds=30)
    ) is True

    assert store.renew_run_execution(
        run.id, "owner", claim.generation, LEASE_NOW - timedelta(seconds=15)
    ) is True

    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT expires_at FROM run_execution_leases WHERE run_id = ?", (run.id,)
        ).fetchone()[0] == "2026-10-01T12:01:30+00:00"


def test_execution_lease_renewal_rejects_expiry_during_writer_lock_wait(tmp_path):
    store = SQLiteStore(tmp_path / "renew-lock.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    claim = store.claim_run_execution(run.id, "owner", LEASE_NOW)
    clock = AdjustableLeaseClock(LEASE_NOW)

    renewed = run_after_writer_lock(
        store, clock,
        lambda: store.renew_run_execution(run.id, "owner", claim.generation, clock),
    )

    assert renewed is False
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT expires_at FROM run_execution_leases WHERE run_id = ?", (run.id,)
        ).fetchone()[0] == "2026-10-01T12:01:00+00:00"


def test_execution_lease_completion_fences_old_generation_after_retry(tmp_path):
    store = SQLiteStore(tmp_path / "fenced.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    first = store.claim_run_execution(run.id, "owner-one", LEASE_NOW)
    store.claim_run_execution(run.id, "other", LEASE_NOW + timedelta(seconds=61))
    retried = store.reset_run_for_retry(run.id)
    assert retried.status == "created"
    assert retried.events[-1] == {"type": "retry_requested", "previous_status": "failed"}
    second = store.claim_run_execution(run.id, "owner-two", LEASE_NOW + timedelta(seconds=62))
    before_stale_completion = store.get_run(run.id)

    stale_result = store.complete_run_execution(
        run.id, "owner-one", first.generation, "completed",
        [{"type": "stale_result"}], [{"name": "stale"}], None,
        LEASE_NOW + timedelta(seconds=63),
    )

    assert stale_result is None
    assert store.get_run(run.id) == before_stale_completion
    assert second.generation > first.generation
    finished = store.complete_run_execution(
        run.id, "owner-two", second.generation, "completed",
        [{"type": "runtime_started"}, {"type": "runtime_finished"}],
        [{"name": "fresh"}], None, LEASE_NOW + timedelta(seconds=64),
    )
    assert finished == store.get_run(run.id)
    assert finished.status == "completed"
    assert finished.artifacts == [{"name": "fresh"}]
    assert [event["type"] for event in finished.events[-2:]] == ["runtime_started", "runtime_finished"]
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT owner_token, generation, expires_at FROM run_execution_leases WHERE run_id = ?",
            (run.id,),
        ).fetchone() == (None, second.generation, None)


def test_execution_lease_completion_rejects_expired_owner_without_writes(tmp_path):
    store = SQLiteStore(tmp_path / "expired-completion.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    claim = store.claim_run_execution(run.id, "owner", LEASE_NOW)

    completed = store.complete_run_execution(
        run.id, "owner", claim.generation, "failed", [{"type": "too_late"}], [], "error",
        LEASE_NOW + timedelta(seconds=60),
    )

    assert completed is None
    assert store.get_run(run.id).status == "running"


def test_execution_lease_completion_rejects_nonterminal_status(tmp_path):
    store = SQLiteStore(tmp_path / "nonterminal-completion.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    claim = store.claim_run_execution(run.id, "owner", LEASE_NOW)

    with pytest.raises(ValueError, match="must be terminal"):
        store.complete_run_execution(
            run.id, "owner", claim.generation, "running", [], [], None, LEASE_NOW,
        )

    assert store.get_run(run.id).status == "running"
    assert store.get_run(run.id).events == []
    assert store.get_run(run.id).events == []


def test_execution_lease_completion_rejects_expiry_during_writer_lock_wait(tmp_path):
    store = SQLiteStore(tmp_path / "complete-lock.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))
    claim = store.claim_run_execution(run.id, "owner", LEASE_NOW)
    clock = AdjustableLeaseClock(LEASE_NOW)

    completed = run_after_writer_lock(
        store, clock,
        lambda: store.complete_run_execution(
            run.id, "owner", claim.generation, "completed",
            [{"type": "too_late"}], [{"name": "stale"}], None, clock,
        ),
    )

    assert completed is None
    persisted = store.get_run(run.id)
    assert persisted.status == "running"
    assert persisted.events == []
    assert persisted.artifacts == []


def test_execution_lease_retry_rejects_non_retryable_status(tmp_path):
    store = SQLiteStore(tmp_path / "invalid-retry.sqlite3")
    store.init()
    run = store.create_run("request", str(tmp_path / "workspace"))

    with pytest.raises(ApprovalError, match="failed or unavailable"):
        store.reset_run_for_retry(run.id)

    assert store.get_run(run.id).status == "created"
