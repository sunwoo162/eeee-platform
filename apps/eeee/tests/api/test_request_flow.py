import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock
from time import monotonic

import pytest
from fastapi.testclient import TestClient

from app.agent.protocol import AgentRequest, AgentResult
from app.api.service import ApiFlowService
from app.config import Settings
from app.domain.models import CandidateScore
from app.main import create_app


def candidate(name: str, total: float) -> CandidateScore:
    return CandidateScore(
        repository={
            "full_name": name,
            "html_url": f"https://github.com/{name}",
            "description": f"A candidate for {name}",
            "stars": 100,
            "forks": 10,
            "open_issues": 2,
            "license_spdx": "MIT",
            "default_branch": "main",
            "pushed_at": "2026-09-28T00:00:00Z",
            "topics": ["web-app"],
        },
        total=total,
        dimension_scores={"fit": total},
        evidence=[f"Evidence for {name}"],
        risks=[],
        status="candidate",
    )


class FakeResearcher:
    def research(self, _brief):
        return [candidate("owner/alpha", 0.9), candidate("owner/beta", 0.8)]


class FakeRuntime:
    def __init__(self):
        self.requests: list[AgentRequest] = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        return AgentResult(
            status="completed",
            summary="Implemented and verified",
            events=[
                {"type": "message", "content": "Implemented"},
                {"type": "verification", "status": "passed"},
            ],
            changed_files=["src/app.py"],
            test_commands=["pytest -q"],
            error=None,
        )


class UnavailableRuntime:
    def run(self, _request: AgentRequest) -> AgentResult:
        return AgentResult(
            status="unavailable",
            summary="OpenHands runtime unavailable",
            events=[],
            changed_files=[],
            test_commands=[],
            error="LLM_API_KEY is not configured",
        )


class BlockingRuntime:
    def __init__(self):
        self.started = Event()
        self.release = Event()
        self.calls = 0

    def run(self, _request: AgentRequest) -> AgentResult:
        self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test runtime was not released")
        return AgentResult(
            status="completed",
            summary="Completed once",
            events=[{"type": "message", "content": "Completed once"}],
            changed_files=[],
            test_commands=[],
            error=None,
        )


class ManualClock:
    def __init__(self):
        self.value = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.lock = Lock()
        self.sampled = Event()

    def __call__(self) -> datetime:
        with self.lock:
            self.sampled.set()
            return self.value

    def advance(self, seconds: int) -> None:
        with self.lock:
            self.value += timedelta(seconds=seconds)


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


def make_approved_services(
    tmp_path: Path, runtime, *, clock=None, heartbeat_interval_seconds=10.0
):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
    )
    first_app = create_app(settings, researcher=FakeResearcher(), agent_runtime=runtime)
    second_app = create_app(settings, researcher=FakeResearcher(), agent_runtime=runtime)
    client = TestClient(first_app)
    created = client.post("/api/requests", json={"text": "Build a web app"}).json()
    assert client.post(f"/api/requests/{created['request_id']}/research").status_code == 200
    assert client.post(
        f"/api/requests/{created['request_id']}/approve",
        json={"selected": ["owner/alpha"]},
    ).status_code == 200
    if clock is None:
        return first_app.state.api_flow, second_app.state.api_flow, created["run_id"]
    first = first_app.state.api_flow
    second = second_app.state.api_flow
    return (
        ApiFlowService(
            first.coordinator, first.store, settings, runtime,
            clock=clock, lease_seconds=60,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        ),
        ApiFlowService(
            second.coordinator, second.store, settings, runtime,
            clock=clock, lease_seconds=60,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        ),
        created["run_id"],
    )


def lease_state(store, run_id: str) -> tuple[int, str | None, str | None] | None:
    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT generation, owner_token, expires_at FROM run_execution_leases WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    return row


def make_client(tmp_path: Path):
    runtime = FakeRuntime()
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
    )
    application = create_app(
        settings,
        researcher=FakeResearcher(),
        agent_runtime=runtime,
    )
    return TestClient(application), runtime


def test_request_research_approval_and_execution_flow(tmp_path):
    client, runtime = make_client(tmp_path)
    workspace = tmp_path / "workspaces" / "sample"

    created = client.post(
        "/api/requests",
        json={"text": "Build a web app", "workspace": str(workspace)},
    )

    assert created.status_code == 200
    created_payload = created.json()
    request_id = created_payload["request_id"]
    run_id = created_payload["run_id"]
    assert created_payload["brief"]["target_type"] == "web_app"
    assert workspace.is_dir()
    transcript = client.app.state.conversation_store.get_transcript("desktop-default")
    assert transcript["turns"][-1]["status"] == "pending"
    assert transcript["turns"][-1]["requestId"] == request_id

    research = client.post(f"/api/requests/{request_id}/research")
    assert research.status_code == 200
    research_payload = research.json()
    assert [item["repository"]["full_name"] for item in research_payload["candidates"]] == [
        "owner/alpha",
        "owner/beta",
    ]
    assert research_payload["work_plan"]["requires_selection"] is True

    blocked = client.post(f"/api/runs/{run_id}/execute")
    assert blocked.status_code == 409
    assert runtime.requests == []

    approved = client.post(
        f"/api/requests/{request_id}/approve",
        json={"selected": ["owner/alpha"]},
    )
    assert approved.status_code == 200
    approved_payload = approved.json()
    assert approved_payload["decision"]["approved"] is True
    assert approved_payload["run_id"] == run_id
    assert approved_payload["decision_events"] == [
        {"action": "approved", "selected": ["owner/alpha"]}
    ]

    executed = client.post(f"/api/runs/{run_id}/execute")
    assert executed.status_code == 200
    run = executed.json()
    assert run["status"] == "completed"
    assert run["error"] is None
    assert run["artifacts"][0]["changed_files"] == ["src/app.py"]
    assert any(event["type"] == "verification" for event in run["events"])
    assert runtime.requests[0].workspace == workspace
    assert runtime.requests[0].allowed_actions == ["read", "workspace_write", "command"]

    fetched = client.get(f"/api/runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json() == run

    retry_completed = client.post(f"/api/runs/{run_id}/retry")
    assert retry_completed.status_code == 409


def test_legacy_request_and_run_routes_are_user_scoped(tmp_path):
    client, _runtime = make_client(tmp_path)
    user_a = {"X-EEEE-User-Id": "user-a"}
    user_b = {"X-EEEE-User-Id": "user-b"}

    created = client.post(
        "/api/requests",
        headers=user_a,
        json={"text": "Build a web app"},
    )
    assert created.status_code == 200
    request_id = created.json()["request_id"]
    run_id = created.json()["run_id"]
    transcript_a = client.app.state.conversation_store.get_transcript(
        "desktop-default", user_id="user-a"
    )
    assert transcript_a["turns"][-1]["requestId"] == request_id
    with pytest.raises(KeyError):
        client.app.state.conversation_store.get_transcript(
            "desktop-default", user_id="user-b"
        )

    assert client.get(f"/api/requests/{request_id}", headers=user_a).status_code == 200
    assert client.get(
        f"/api/requests/{request_id}/project-brief", headers=user_a
    ).status_code == 200
    assert client.post(
        f"/api/requests/{request_id}/research", headers=user_a
    ).status_code == 200
    assert client.post(
        f"/api/requests/{request_id}/approve",
        headers=user_a,
        json={"selected": ["owner/alpha"]},
    ).status_code == 200
    assert client.get(f"/api/runs/{run_id}", headers=user_a).status_code == 200

    assert client.get(f"/api/requests/{request_id}", headers=user_b).status_code == 404
    assert client.get(
        f"/api/requests/{request_id}/project-brief", headers=user_b
    ).status_code == 404
    assert client.post(
        f"/api/requests/{request_id}/research", headers=user_b
    ).status_code == 404
    assert client.post(
        f"/api/requests/{request_id}/approve",
        headers=user_b,
        json={"selected": ["owner/alpha"]},
    ).status_code == 404
    assert client.get(f"/api/runs/{run_id}", headers=user_b).status_code == 404
    assert client.post(f"/api/runs/{run_id}/execute", headers=user_b).status_code == 404
    assert client.post(f"/api/runs/{run_id}/retry", headers=user_b).status_code == 404
    assert client.get("/api/runs", headers=user_b).json() == []


def test_legacy_request_can_join_a_named_assistant_conversation(tmp_path):
    client, _runtime = make_client(tmp_path)

    created = client.post(
        "/api/requests",
        json={
            "text": "Build a web app",
            "conversationId": "project-planning-chat",
        },
    )

    assert created.status_code == 200
    request_id = created.json()["request_id"]
    transcript = client.app.state.conversation_store.get_transcript("project-planning-chat")
    assert transcript["turns"][-1]["requestId"] == request_id
    assert transcript["turns"][-1]["status"] == "pending"


def test_concurrent_execution_requests_only_start_one_runtime_call(tmp_path):
    class BlockingRuntime:
        def __init__(self):
            self.started = Event()
            self.release = Event()
            self.calls = 0

        def run(self, _request: AgentRequest) -> AgentResult:
            self.calls += 1
            self.started.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("test runtime was not released")
            return AgentResult(
                status="completed",
                summary="Completed once",
                events=[],
                changed_files=[],
                test_commands=[],
                error=None,
            )

    runtime = BlockingRuntime()
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
    )
    client = TestClient(create_app(settings, researcher=FakeResearcher(), agent_runtime=runtime))
    created = client.post("/api/requests", json={"text": "Build a web app"}).json()
    request_id = created["request_id"]
    run_id = created["run_id"]
    assert client.post(f"/api/requests/{request_id}/research").status_code == 200
    assert client.post(
        f"/api/requests/{request_id}/approve", json={"selected": ["owner/alpha"]}
    ).status_code == 200

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_request = executor.submit(client.post, f"/api/runs/{run_id}/execute")
        assert runtime.started.wait(timeout=5), "the first execution should reach the runtime"
        duplicate_request = executor.submit(client.post, f"/api/runs/{run_id}/execute")
        try:
            duplicate_response = duplicate_request.result(timeout=3)
        finally:
            runtime.release.set()
        first_response = first_request.result(timeout=5)

    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["status"] == "running"
    assert first_response.status_code == 200
    assert first_response.json()["status"] == "completed"
    assert runtime.calls == 1


def test_cross_instance_execute_only_invokes_runtime_once(tmp_path):
    runtime = BlockingRuntime()
    first, second, run_id = make_approved_services(tmp_path, runtime)
    assert first.store is not second.store

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_result = executor.submit(first.execute, run_id)
        assert runtime.started.wait(timeout=5)
        try:
            duplicate = second.execute(run_id)
            assert duplicate.status == "running"
            assert runtime.calls == 1
        finally:
            runtime.release.set()
        completed = first_result.result(timeout=5)

    assert completed.status == "completed"
    assert runtime.calls == 1
    assert second.get_run(run_id).status == "completed"


def test_execute_claim_samples_clock_after_writer_lock(tmp_path):
    runtime = BlockingRuntime()
    clock = ManualClock()
    first, _second, run_id = make_approved_services(tmp_path, runtime, clock=clock)
    original_connect = first.store._connect
    begin_attempted = Event()
    first.store._connect = lambda: BeginTrackedConnection(original_connect(), begin_attempted)
    try:
        with sqlite3.connect(first.store.path) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(first.execute, run_id)
                try:
                    try:
                        assert begin_attempted.wait(timeout=2)
                        assert not clock.sampled.is_set(), "clock sampled before writer lock"
                        clock.advance(61)
                    finally:
                        writer.rollback()
                    assert runtime.started.wait(timeout=5)
                    assert lease_state(first.store, run_id)[2] == "2026-10-01T00:02:01+00:00"
                finally:
                    runtime.release.set()
                assert future.result(timeout=5).status == "completed"
    finally:
        first.store._connect = original_connect


def test_heartbeat_renews_long_running_execution(tmp_path):
    runtime = BlockingRuntime()
    clock = ManualClock()
    first, second, run_id = make_approved_services(
        tmp_path, runtime, clock=clock, heartbeat_interval_seconds=0.01
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_result = executor.submit(first.execute, run_id)
        assert runtime.started.wait(timeout=5)
        initial_expiry = lease_state(first.store, run_id)[2]
        clock.advance(40)
        try:
            deadline = monotonic() + 2
            while lease_state(first.store, run_id)[2] == initial_expiry:
                assert monotonic() < deadline, "heartbeat did not renew"
                Event().wait(0.01)
            clock.advance(21)
            assert second.execute(run_id).status == "running"
            assert runtime.calls == 1
        finally:
            runtime.release.set()
        assert first_result.result(timeout=5).status == "completed"


def test_expired_execution_fails_without_invoking_runtime_again(tmp_path):
    runtime = BlockingRuntime()
    clock = ManualClock()
    first, second, run_id = make_approved_services(tmp_path, runtime, clock=clock)

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_result = executor.submit(first.execute, run_id)
        assert runtime.started.wait(timeout=5)
        clock.advance(61)
        try:
            expired = second.execute(run_id)
        finally:
            runtime.release.set()
        old_result = first_result.result(timeout=5)

    assert expired.status == "failed"
    assert "partial changes" in expired.error
    assert any(event["type"] == "execution_expired" for event in expired.events)
    assert old_result.status == "failed"
    assert runtime.calls == 1
    assert not any(event.get("content") == "Completed once" for event in old_result.events)


def test_legacy_running_row_without_lease_fails_on_execute(tmp_path):
    runtime = FakeRuntime()
    first, second, run_id = make_approved_services(tmp_path, runtime)
    first.store.update_run(run_id, status="running", artifacts=[], error=None)

    recovered = second.execute(run_id)

    assert recovered.status == "failed"
    assert "partial changes" in recovered.error
    assert any(event["type"] == "execution_stale" for event in recovered.events)
    assert runtime.requests == []


def test_retry_resets_failed_run_and_advances_generation_without_runtime(tmp_path):
    runtime = FakeRuntime()
    first, second, run_id = make_approved_services(tmp_path, runtime)
    assert first.execute(run_id).status == "completed"
    generation_before = lease_state(first.store, run_id)[0]
    requests_before_retry = len(runtime.requests)
    first.store.update_run(run_id, status="failed", artifacts=[{"type": "old"}], error="old")

    retried = second.retry(run_id)

    assert retried.status == "created"
    assert retried.artifacts == []
    assert retried.error is None
    assert retried.events[-1] == {"type": "retry_requested", "previous_status": "failed"}
    assert lease_state(second.store, run_id)[0] == generation_before + 1
    assert len(runtime.requests) == requests_before_retry


def test_nonterminal_runtime_result_is_failed_and_releases_ownership(tmp_path):
    class NonterminalRuntime:
        def run(self, _request: AgentRequest) -> AgentResult:
            return AgentResult(
                status="running",
                summary="Unexpected intermediate result",
                events=[{"type": "message", "content": "Partial work"}],
                changed_files=[],
                test_commands=[],
                error=None,
            )

    first, second, run_id = make_approved_services(tmp_path, NonterminalRuntime())

    result = first.execute(run_id)

    assert result.status == "failed"
    assert result.error is not None
    assert lease_state(second.store, run_id)[1] is None


def test_post_runtime_failure_requires_explicit_retry(tmp_path):
    class FailingArtifactWriter:
        def write_run_bundle(self, *_args, **_kwargs):
            raise OSError("workspace is read-only")

    runtime = FakeRuntime()
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
    )
    application = create_app(settings, researcher=FakeResearcher(), agent_runtime=runtime)
    application.state.api_flow.artifacts = FailingArtifactWriter()
    client = TestClient(application, raise_server_exceptions=False)
    created = client.post("/api/requests", json={"text": "Build a web app"}).json()
    request_id = created["request_id"]
    run_id = created["run_id"]
    assert client.post(f"/api/requests/{request_id}/research").status_code == 200
    assert client.post(
        f"/api/requests/{request_id}/approve", json={"selected": ["owner/alpha"]}
    ).status_code == 200

    failed = client.post(f"/api/runs/{run_id}/execute")
    assert failed.status_code == 500
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "failed"

    duplicate = client.post(f"/api/runs/{run_id}/execute")
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "failed"
    assert len(runtime.requests) == 1

    retried = client.post(f"/api/runs/{run_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "created"
    retry_failure = client.post(f"/api/runs/{run_id}/execute")
    assert retry_failure.status_code == 500
    assert len(runtime.requests) == 2


def test_request_api_serves_local_ui_and_missing_run_is_not_found(tmp_path):
    client, _runtime = make_client(tmp_path)

    page = client.get("/")
    assert page.status_code == 200
    assert "Gleave" in page.text
    assert "/static/app.js" in page.text
    assert '<link rel="icon" href="/static/favicon.svg" type="image/svg+xml" />' in page.text
    assert "Restore saved request" in page.text
    assert "Work plan" in page.text
    assert "Approval history" in page.text
    assert "Run history" in page.text
    assert "Recent runs" in page.text
    assert '<h3 id="candidate-selection-heading">Candidate evidence and selection</h3>' in page.text
    assert 'id="candidates" class="candidate-grid" aria-labelledby="candidate-selection-heading" aria-live="polite" aria-busy="false"' in page.text
    assert '<h2 id="run-heading">3. Execute and verify</h2>' in page.text
    assert '<h3 id="recent-runs-heading">Recent runs</h3>' in page.text
    assert 'id="recent-run-search"' in page.text
    assert 'id="recent-run-status-filter"' in page.text
    assert 'id="recent-run-created-after"' in page.text
    assert 'id="recent-run-created-before"' in page.text
    assert 'id="recent-run-page-size"' in page.text
    assert 'id="recent-run-sort"' in page.text
    assert 'id="refresh-recent-runs"' in page.text
    assert 'id="clear-recent-run-filters"' in page.text
    assert 'id="recent-runs-status"' in page.text
    assert 'id="test-commands"' in page.text
    assert 'id="run-artifacts"' in page.text
    assert 'id="status" class="status" role="status" aria-live="polite"' in page.text
    assert 'id="design-status" class="status" role="status" aria-live="polite"' in page.text
    assert 'id="visual-status" class="muted" role="status" aria-live="polite"' in page.text
    assert 'id="run-summary" class="muted" role="status" aria-live="polite"' in page.text
    assert 'id="restore-status" class="muted" role="status" aria-live="polite"' in page.text
    assert 'id="recent-runs-status" class="muted" role="status" aria-live="polite"' in page.text
    assert 'id="events" class="event-list" role="log" aria-live="polite"' in page.text
    assert 'id="changed-files" class="file-list" aria-label="Changed files"' in page.text
    assert 'id="test-commands" class="file-list" aria-label="Test commands"' in page.text
    assert 'id="run-artifacts" class="file-list" aria-label="Run artifacts"' in page.text
    assert 'id="recent-runs" class="run-history" aria-label="Recent runs"' in page.text
    assert 'id="run-history" class="run-history" aria-label="Run history"' in page.text
    assert 'id="design-form" aria-busy="false"' in page.text
    assert 'id="visual-form" class="visual-form" aria-busy="false"' in page.text
    assert 'id="candidates" class="candidate-grid" aria-labelledby="candidate-selection-heading" aria-live="polite"' in page.text
    assert 'id="references" class="reference-list" aria-label="Design references" aria-live="polite"' in page.text
    assert 'id="tokens" class="code-panel" aria-label="Design tokens" aria-live="polite"' in page.text
    assert 'id="attribution" class="muted" aria-label="Attribution" aria-live="polite"' in page.text

    app_script = client.get("/static/app.js")
    assert app_script.status_code == 200
    app_script_text = app_script.text.replace("\r\n", "\n")
    assert 'setRunTimeFilter(params, "created_after"' in app_script_text
    assert 'setRunTimeFilter(params, "created_before"' in app_script_text
    assert 'clearRunHistoryFilters' in app_script_text
    assert 'clearTimeout(recentRunsSearchTimer)' in app_script_text
    assert 'RECENT_RUN_FILTERS_STORAGE_KEY' in app_script_text
    assert 'restoreRecentRunFilters()' in app_script_text
    assert 'localStorage.setItem(RECENT_RUN_FILTERS_STORAGE_KEY' in app_script_text
    assert 'localStorage.removeItem(RECENT_RUN_FILTERS_STORAGE_KEY' in app_script_text
    assert 'function refreshRecentRunsForFilterChange()' in app_script_text
    assert 'clearTimeout(recentRunsSearchTimer);\n  saveRecentRunFilters();\n  refreshRecentRuns();' in app_script_text
    assert 'addEventListener("click", refreshRecentRunsForFilterChange)' in app_script_text
    assert 'runsUpdatedAt' in app_script_text
    assert 'License ${repository.license_spdx || "unknown"}' in app_script_text
    assert 'repository.stars.toLocaleString()' in app_script_text
    assert 'repository.forks.toLocaleString()' in app_script_text
    assert 'Object.entries(candidate.dimension_scores)' in app_script_text
    assert 'candidate.risks.length ?' in app_script_text
    assert "selectedCandidates: null" in app_script_text
    assert 'snapshot.decision ? snapshot.decision.selected : null' in app_script_text
    assert 'checkbox.checked = state.selectedCandidates === null' in app_script_text
    assert 'checkbox.disabled = state.approved' in app_script_text
    assert 'checkbox.addEventListener("change"' in app_script_text
    assert 'if (!state.approved) state.selectedCandidates = null;' in app_script_text
    assert (
        'state.approved = result.decision.approved;\n'
        '    state.selectedCandidates = result.decision.selected;\n'
        '    state.decisionEvents = result.decision_events || [];\n'
        '    if (!preserveRunSelection) setSelectedRun(result.run_id);\n'
        '    renderCandidates();\n'
        '    renderDecisionEvents(state.decisionEvents);\n'
        '    $("#research-button").disabled = state.approved;\n'
        '    $("#run-button").disabled = !state.approved;\n'
        '    if (!preserveRunSelection) {\n'
        '      $("#run-summary").textContent = "Selection approved. Execution is ready.";\n'
        '    }\n'
        '    const snapshot = await requestJson'
    ) in app_script_text
    assert '$("#research-button").disabled = state.approved;' in app_script_text
    assert 'Approval saved. Request refresh failed:' in app_script_text
    assert "decisionEvents: []" in app_script_text
    assert 'state.decisionEvents = [];' in app_script_text
    assert 'state.decisionEvents = snapshot.decision_events || [];' in app_script_text
    assert 'decision_events: state.approved ? state.decisionEvents : []' in app_script_text
    assert (
        'state.decisionEvents = result.decision_events || [];\n'
        '    if (!preserveRunSelection) setSelectedRun(result.run_id);\n'
        '    renderCandidates();\n'
        '    renderDecisionEvents(state.decisionEvents);'
    ) in app_script_text
    assert app_script_text.count("button.dataset.runId = run.id;") == 2
    assert 'function setSelectedRun(runId)' in app_script_text
    assert 'setSelectedRun(run.id);\n      renderRun(run);' in app_script_text
    assert 'setSelectedRun(run.id);\n    renderRun(run);' in app_script_text
    assert 'Showing ${loadedRuns ? `1–${loadedRuns}` : "0"} of ${state.totalRuns} matching runs' in app_script_text
    assert 'No runs match the current filters (0 total).' in app_script_text
    assert 'state.runsError && loadedRuns' in app_script_text
    assert 'if (!state.hasLoadedRuns || state.loadingRuns) return;' in app_script_text
    assert 'state.hasLoadedRuns = true;' in app_script_text
    assert 'Updated ${formatRunTime(state.runsUpdatedAt)}' in app_script_text
    assert 'RECENT_RUN_PAGE_SIZES' in app_script_text
    assert 'pageSize: $("#recent-run-page-size").value' in app_script_text
    assert '$("#recent-run-page-size").addEventListener("change", refreshRecentRunsForFilterChange)' in app_script_text
    assert 'typeof value === "string"' in app_script_text
    assert 'Number.isInteger(value)' in app_script_text
    assert 'RECENT_RUN_SORTS' in app_script_text
    assert 'sort: $("#recent-run-sort").value' in app_script_text
    assert 'params.set("sort", sort)' in app_script_text

    missing = client.get("/api/runs/missing-run")
    assert missing.status_code == 404


def test_ui_ignores_research_response_after_switching_requests(tmp_path):
    client, _runtime = make_client(tmp_path)

    app_script = client.get("/static/app.js").text.replace("\r\n", "\n")
    research_handler = app_script.split(
        '$("#research-button").addEventListener("click", async () => {', 1
    )[1].split('\n$("#approve-button").addEventListener', 1)[0]

    assert "const requestId = state.requestId;" in research_handler
    assert "`/api/requests/${requestId}/research`" in research_handler
    assert research_handler.index("if (state.requestId !== requestId) return;") < research_handler.index(
        "state.candidates = result.candidates;"
    )
    assert "if (state.requestId === requestId) showError(error);" in research_handler


def test_ui_ignores_approval_response_after_switching_requests(tmp_path):
    client, _runtime = make_client(tmp_path)

    app_script = client.get("/static/app.js").text.replace("\r\n", "\n")
    approval_handler = app_script.split(
        '$("#approve-button").addEventListener("click", async () => {', 1
    )[1].split('\n$("#design-form").addEventListener', 1)[0]

    assert "const requestId = state.requestId;" in approval_handler
    assert "const selectionId = state.requestSelectionId;" in approval_handler
    assert '`/api/requests/${requestId}/approve`' in approval_handler
    assert "const preserveRunSelection = state.requestSelectionId !== selectionId;" in approval_handler
    assert "if (!preserveRunSelection) setSelectedRun(result.run_id);" in approval_handler
    assert "const selectedRunId = state.requestSelectionId !== selectionId ? state.runId : result.run_id;" in approval_handler
    assert "renderRun(selectedRun);" in approval_handler
    assert "if (state.requestId !== requestId) return;" in approval_handler.split(
        "} catch (error) {", 1
    )[1]
    assert "else if (state.requestSelectionId !== selectionId)" in approval_handler


def test_ui_approval_responses_do_not_override_newer_run_selection(tmp_path):
    client, _runtime = make_client(tmp_path)
    app_script = client.get("/static/app.js").text
    test_script = Path(__file__).resolve().parents[1] / "ui_approval_selection_race.js"

    result = subprocess.run(
        [
            "node",
            "--input-type=commonjs",
            "--eval",
            "eval(require('node:fs').readFileSync(process.argv[1], 'utf8'))",
            str(test_script),
        ],
        input=app_script,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_ui_ignores_run_action_responses_after_switching_runs(tmp_path):
    client, _runtime = make_client(tmp_path)

    app_script = client.get("/static/app.js").text.replace("\r\n", "\n")
    run_handler = app_script.split(
        '$("#run-button").addEventListener("click", async () => {', 1
    )[1].split('\n$("#restore-form").addEventListener', 1)[0]
    retry_handler = app_script.split(
        '$("#retry-button").addEventListener("click", async () => {', 1
    )[1]

    for handler, action in ((run_handler, "execute"), (retry_handler, "retry")):
        assert "const runId = state.runId;" in handler
        assert f"`/api/runs/${{runId}}/{action}`" in handler
        assert "if (state.runId !== runId)" in handler
        assert "if (state.requestId === run.request_id) {" in handler
        response_guard = handler.index("if (state.runId !== runId)")
        assert handler.index("renderRunHistory(state.runs);") < response_guard
        assert handler.index("refreshRecentRuns();") < response_guard
        assert "if (state.runId !== runId)" in handler.split("} catch (error) {", 1)[1]
    assert "function backgroundRunStatus(runId)" in app_script
    assert 'setStatus(backgroundRunStatus(state.runId), "busy");' in app_script
    assert 'if ($("#status").textContent === backgroundStatus' in run_handler


def test_ui_ignores_stale_request_selection_responses(tmp_path):
    client, _runtime = make_client(tmp_path)

    app_script = client.get("/static/app.js").text.replace("\r\n", "\n")
    assert "requestSelectionId: 0" in app_script
    selection_helper = app_script.split("function beginRequestSelection() {", 1)[1].split(
        "async function requestJson", 1
    )[0]
    assert 'if ($("#restore-status").textContent === "Restoring…")' in selection_helper
    assert 'if ($("#recent-runs-status").textContent === "Loading selected run…")' in selection_helper
    assert 'if ($("#status").textContent === "Creating request…")' in selection_helper
    history_handler = app_script.split("function renderRunHistory(runs) {", 1)[1].split(
        "function renderRecentRuns()", 1
    )[0]
    assert 'beginRequestSelection();\n      setSelectedRun(run.id);' in history_handler

    create_handler = app_script.split(
        '$("#request-form").addEventListener("submit", async (event) => {', 1
    )[1].split('\n$("#research-button").addEventListener', 1)[0]
    assert "const selectionId = beginRequestSelection();" in create_handler
    assert create_handler.index("if (state.requestSelectionId !== selectionId) return;") < create_handler.index(
        "state.requestId = created.request_id;"
    )
    assert "if (state.requestSelectionId === selectionId) showError(error);" in create_handler

    restore_handler = app_script.split(
        "async function restoreRequest(requestId, quiet = false) {", 1
    )[1].split("\nfunction applySnapshot", 1)[0]
    assert "const selectionId = beginRequestSelection();" in restore_handler
    assert restore_handler.index("if (state.requestSelectionId !== selectionId) return false;") < restore_handler.index(
        "applySnapshot(snapshot);"
    )
    assert "if (state.requestSelectionId !== selectionId) return false;" in restore_handler.split(
        "} catch (error) {", 1
    )[1]

    recent_run_handler = app_script.split(
        "async function openRecentRun(run) {", 1
    )[1].split("\nfunction renderDecisionEvents", 1)[0]
    assert "const selectionId = beginRequestSelection();" in recent_run_handler
    assert recent_run_handler.index("if (state.requestSelectionId !== selectionId) return;") < recent_run_handler.index(
        "applySnapshot(snapshot);"
    )
    assert "if (state.requestSelectionId !== selectionId) return;" in recent_run_handler.split(
        "} catch (error) {", 1
    )[1]


def test_ui_design_tools_ignore_stale_responses(tmp_path):
    client, _runtime = make_client(tmp_path)
    app_script = client.get("/static/app.js").text
    test_script = Path(__file__).resolve().parents[1] / "ui_design_tool_races.js"

    result = subprocess.run(
        [
            "node",
            "--input-type=commonjs",
            "--eval",
            "eval(require('node:fs').readFileSync(process.argv[1], 'utf8'))",
            str(test_script),
        ],
        input=app_script,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_request_rejects_workspace_outside_configured_root(tmp_path):
    client, _runtime = make_client(tmp_path)

    response = client.post(
        "/api/requests",
        json={"text": "Build a web app", "workspace": str(tmp_path / "outside")},
    )

    assert response.status_code == 400
    assert "inside the configured workspace root" in response.json()["detail"]


def test_unavailable_runtime_persists_error_state(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
    )
    client = TestClient(
        create_app(settings, researcher=FakeResearcher(), agent_runtime=UnavailableRuntime())
    )
    created = client.post("/api/requests", json={"text": "Build a web app"}).json()
    client.post(f"/api/requests/{created['request_id']}/research")
    client.post(
        f"/api/requests/{created['request_id']}/approve",
        json={"selected": ["owner/alpha"]},
    )

    result = client.post(f"/api/runs/{created['run_id']}/execute")

    assert result.status_code == 200
    assert result.json()["status"] == "unavailable"
    assert result.json()["error"] == "LLM_API_KEY is not configured"


def test_unavailable_run_can_be_retried_after_runtime_configuration_changes(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
    )
    first_client = TestClient(
        create_app(settings, researcher=FakeResearcher(), agent_runtime=UnavailableRuntime())
    )
    created = first_client.post("/api/requests", json={"text": "Build a web app"}).json()
    first_client.post(f"/api/requests/{created['request_id']}/research")
    first_client.post(
        f"/api/requests/{created['request_id']}/approve",
        json={"selected": ["owner/alpha"]},
    )
    unavailable = first_client.post(f"/api/runs/{created['run_id']}/execute")
    assert unavailable.json()["status"] == "unavailable"

    restarted_client = TestClient(
        create_app(settings, researcher=FakeResearcher(), agent_runtime=FakeRuntime())
    )
    retried = restarted_client.post(f"/api/runs/{created['run_id']}/retry")

    assert retried.status_code == 200
    assert retried.json()["status"] == "created"
    assert retried.json()["error"] is None
    assert retried.json()["events"][-1]["type"] == "retry_requested"

    completed = restarted_client.post(f"/api/runs/{created['run_id']}/execute")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_run_history_lists_persisted_runs_for_a_request(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
    )
    client = TestClient(create_app(settings, researcher=FakeResearcher(), agent_runtime=FakeRuntime()))
    created = client.post("/api/requests", json={"text": "Build a web app"}).json()

    history = client.get(f"/api/runs?request_id={created['request_id']}")

    assert history.status_code == 200
    listed = history.json()
    assert len(listed) == 1
    assert listed[0]["id"] == created["run_id"]
    assert listed[0]["request_id"] == created["request_id"]
    assert listed[0]["status"] == "created"
    assert listed[0]["events"] == []
    assert listed[0]["artifacts"] == []
    assert listed[0]["error"] is None
    assert history.headers["x-total-count"] == "1"

    restarted = TestClient(create_app(settings, researcher=FakeResearcher(), agent_runtime=FakeRuntime()))
    restarted_history = restarted.get(f"/api/runs?request_id={created['request_id']}")
    assert restarted_history.status_code == 200
    assert restarted_history.json()[0]["id"] == created["run_id"]


def test_run_history_pagination_preserves_list_response_and_reports_more(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings, researcher=FakeResearcher(), agent_runtime=FakeRuntime()))
    first = client.post("/api/requests", json={"text": "First"}).json()
    second = client.post("/api/requests", json={"text": "Second"}).json()

    page = client.get("/api/runs", params={"limit": 1, "offset": 0})
    next_page = client.get("/api/runs", params={"limit": 1, "offset": 1})

    assert page.status_code == 200
    assert isinstance(page.json(), list)
    assert [run["id"] for run in page.json()] == [second["run_id"]]
    assert page.headers["x-has-more"] == "true"
    assert [run["id"] for run in next_page.json()] == [first["run_id"]]
    assert next_page.headers["x-has-more"] == "false"


def test_run_history_can_be_sorted_oldest_first(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings, researcher=FakeResearcher(), agent_runtime=FakeRuntime()))
    created_runs = [
        client.post("/api/requests", json={"text": f"Request {index}"}).json()
        for index in range(3)
    ]

    oldest = client.get("/api/runs", params={"sort": "oldest", "limit": 2})
    invalid = client.get("/api/runs", params={"sort": "random"})

    assert oldest.status_code == 200
    assert [run["id"] for run in oldest.json()] == [
        created_runs[0]["run_id"], created_runs[1]["run_id"]
    ]
    assert oldest.headers["x-total-count"] == "3"
    assert oldest.headers["x-has-more"] == "true"
    assert invalid.status_code == 422


def test_run_history_filters_before_paginating(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings, researcher=FakeResearcher(), agent_runtime=FakeRuntime()))
    created_runs = [
        client.post("/api/requests", json={"text": f"Request {index}"}).json()
        for index in range(3)
    ]

    first_page = client.get("/api/runs", params={"status": "created", "limit": 2})
    second_page = client.get("/api/runs", params={"status": "created", "limit": 2, "offset": 2})
    by_id = client.get(
        "/api/runs",
        params={"status": "created", "search": created_runs[0]["run_id"][:8]},
    )

    assert [run["id"] for run in first_page.json()] == [
        created_runs[2]["run_id"], created_runs[1]["run_id"]
    ]
    assert first_page.headers["x-total-count"] == "3"
    assert first_page.headers["x-has-more"] == "true"
    assert [run["id"] for run in second_page.json()] == [created_runs[0]["run_id"]]
    assert second_page.headers["x-total-count"] == "3"
    assert second_page.headers["x-has-more"] == "false"
    assert [run["id"] for run in by_id.json()] == [created_runs[0]["run_id"]]
    assert by_id.headers["x-total-count"] == "1"


def test_run_history_pagination_reports_total_matching_count(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings, researcher=FakeResearcher(), agent_runtime=FakeRuntime()))
    for index in range(3):
        client.post("/api/requests", json={"text": f"Request {index}"})

    page = client.get("/api/runs", params={"limit": 1})

    assert page.status_code == 200
    assert page.headers["x-total-count"] == "3"


def test_run_history_filters_by_creation_time(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings, researcher=FakeResearcher(), agent_runtime=FakeRuntime()))
    created_runs = [
        client.post("/api/requests", json={"text": f"Request {index}"}).json()
        for index in range(3)
    ]
    first_created_at = client.get(
        "/api/runs", params={"request_id": created_runs[0]["request_id"]}
    ).json()[0]["created_at"]
    last_created_at = client.get(
        "/api/runs", params={"request_id": created_runs[2]["request_id"]}
    ).json()[0]["created_at"]
    first_created_at_seoul = datetime.fromisoformat(first_created_at).astimezone(
        timezone(timedelta(hours=9))
    ).isoformat()

    before_first = client.get(
        "/api/runs",
        params={"created_before": first_created_at, "limit": 1},
    )
    after_first = client.get(
        "/api/runs",
        params={"created_after": first_created_at_seoul, "limit": 1},
    )
    combined = client.get(
        "/api/runs",
        params={
            "status": "created",
            "search": created_runs[1]["run_id"][:8],
            "created_after": first_created_at,
            "limit": 1,
        },
    )
    reversed_range = client.get(
        "/api/runs",
        params={
            "created_after": last_created_at,
            "created_before": first_created_at,
            "limit": 1,
        },
    )
    invalid = client.get(
        "/api/runs", params={"created_after": "not-a-timestamp"}
    )

    assert [run["id"] for run in before_first.json()] == [created_runs[0]["run_id"]]
    assert before_first.headers["x-total-count"] == "1"
    assert before_first.headers["x-has-more"] == "false"
    assert [run["id"] for run in after_first.json()] == [created_runs[2]["run_id"]]
    assert after_first.headers["x-total-count"] == "3"
    assert after_first.headers["x-has-more"] == "true"
    assert [run["id"] for run in combined.json()] == [created_runs[1]["run_id"]]
    assert combined.headers["x-total-count"] == "1"
    assert combined.headers["x-has-more"] == "false"
    assert reversed_range.json() == []
    assert reversed_range.headers["x-total-count"] == "0"
    assert reversed_range.headers["x-has-more"] == "false"
    assert invalid.status_code == 422


def test_run_history_rejects_unknown_status_filter(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings, researcher=FakeResearcher(), agent_runtime=FakeRuntime()))

    response = client.get("/api/runs", params={"status": "not-a-status", "limit": 10})

    assert response.status_code == 422


def test_request_snapshot_restores_candidates_decision_and_runs_after_restart(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
    )
    client = TestClient(create_app(settings, researcher=FakeResearcher(), agent_runtime=FakeRuntime()))
    created = client.post(
        "/api/requests",
        json={"text": "Build a web app", "workspace": str(tmp_path / "workspaces" / "sample")},
    ).json()
    client.post(f"/api/requests/{created['request_id']}/research")
    client.post(
        f"/api/requests/{created['request_id']}/approve",
        json={"selected": ["owner/alpha"]},
    )

    snapshot = client.get(f"/api/requests/{created['request_id']}")

    assert snapshot.status_code == 200
    payload = snapshot.json()
    assert payload["request_id"] == created["request_id"]
    assert payload["project_id"].startswith("api-")
    assert payload["workspace"].endswith("sample")
    assert [item["repository"]["full_name"] for item in payload["candidates"]] == [
        "owner/alpha",
        "owner/beta",
    ]
    assert payload["decision"]["approved"] is True
    assert payload["decision"]["selected"] == ["owner/alpha"]
    assert payload["decision_events"] == [
        {"action": "approved", "selected": ["owner/alpha"]}
    ]
    assert [step["id"] for step in payload["work_plan"]["steps"]] == [
        "confirm",
        "research",
        "compare",
        "approve",
        "implement",
        "verify",
    ]
    assert [run["id"] for run in payload["runs"]] == [created["run_id"]]
    assert payload["runs"][0]["status"] == "created"

    restarted = TestClient(create_app(settings, researcher=FakeResearcher(), agent_runtime=FakeRuntime()))
    restored = restarted.get(f"/api/requests/{created['request_id']}")

    assert restored.status_code == 200
    assert restored.json() == payload


def test_request_snapshot_missing_request_is_not_found(tmp_path):
    client, _runtime = make_client(tmp_path)

    response = client.get("/api/requests/missing-request")

    assert response.status_code == 404
