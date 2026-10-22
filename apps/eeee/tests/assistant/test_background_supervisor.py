import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.assistant.background import BackgroundExecutionSupervisor
from app.assistant.background import JobTransitionError
from app.storage.sqlite import SQLiteStore


def _wait_for(supervisor, job_id: str, status: str) -> dict[str, object]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = supervisor.get(job_id)
        if job["status"] == status:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job did not reach {status}: {supervisor.get(job_id)}")


def test_background_job_is_durable_and_reports_completed_result(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    supervisor = BackgroundExecutionSupervisor(store, max_workers=1)
    try:
        job_id = supervisor.submit(
            "assistant-request-1",
            lambda: {"message": "todo project accepted", "projectId": "project-1"},
        )

        job = _wait_for(supervisor, job_id, "completed")
        assert job["requestId"] == "assistant-request-1"
        assert job["result"] == {"message": "todo project accepted", "projectId": "project-1"}

        restarted = BackgroundExecutionSupervisor(store, max_workers=1)
        try:
            assert restarted.get(job_id) == job
        finally:
            restarted.shutdown()
    finally:
        supervisor.shutdown()


def test_background_job_failure_is_recorded_without_claiming_success(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    supervisor = BackgroundExecutionSupervisor(store, max_workers=1)
    try:
        job_id = supervisor.submit(
            "assistant-request-2",
            lambda: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
        )

        job = _wait_for(supervisor, job_id, "failed")
        assert job["result"] is None
        assert job["error"] == "provider unavailable"
    finally:
        supervisor.shutdown()


def test_background_job_status_can_be_read_after_submission(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    supervisor = BackgroundExecutionSupervisor(store, max_workers=1)
    try:
        job_id = supervisor.submit("assistant-request-3", lambda: {"ok": True})
        assert supervisor.get(job_id)["status"] in {"queued", "running", "completed"}
    finally:
        supervisor.shutdown()


def test_concurrent_submit_with_same_request_id_reuses_one_durable_job(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    supervisor = BackgroundExecutionSupervisor(store, max_workers=1)
    started = Event()
    release = Event()

    def operation():
        started.set()
        release.wait(timeout=3)
        return {"ok": True}

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            job_ids = list(
                pool.map(
                    lambda _index: supervisor.submit(
                        "assistant-request-concurrent", operation
                    ),
                    range(8),
                )
            )

        assert len(set(job_ids)) == 1
        assert started.wait(timeout=3)
        release.set()
        assert _wait_for(supervisor, job_ids[0], "completed")["result"] == {"ok": True}
        assert len(supervisor.list_jobs()) == 1
    finally:
        release.set()
        supervisor.shutdown()


def test_pending_job_can_be_resumed_by_a_new_supervisor(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    first = BackgroundExecutionSupervisor(store, max_workers=1)
    job_id = "assistant-job-recover"
    first._create(
        job_id,
        "assistant-request-recover",
        {"text": "resume me"},
    )
    first.shutdown()

    second = BackgroundExecutionSupervisor(store, max_workers=1)
    try:
        resumed = second.resume_pending(
            lambda job: lambda: {"message": job["input"]["text"]},
        )
        assert job_id in resumed
        job = _wait_for(second, job_id, "completed")
        assert job["result"] == {"message": "resume me"}
    finally:
        second.shutdown()


def test_restart_recovers_running_job_before_previous_lease_expires(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    first = BackgroundExecutionSupervisor(store, max_workers=1)
    job_id = "assistant-job-restart-running"
    try:
        first._create(job_id, "assistant-request-restart-running", {"text": "resume now"})
        with store._connect() as connection:
            connection.execute(
                "UPDATE assistant_jobs SET status = 'running', lease_owner = ?, "
                "lease_expires_at = ? WHERE job_id = ?",
                (first._owner_token, "2999-01-01T00:00:00+00:00", job_id),
            )
    finally:
        first.shutdown()

    second = BackgroundExecutionSupervisor(store, max_workers=1)
    try:
        resumed = second.resume_pending(
            lambda job: lambda: {"message": job["input"]["text"]},
        )
        assert resumed == [job_id]
        assert _wait_for(second, job_id, "completed")["result"] == {"message": "resume now"}
    finally:
        second.shutdown()


def test_running_job_can_be_paused_and_resumed_without_losing_input(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    supervisor = BackgroundExecutionSupervisor(store, max_workers=1)
    started = Event()
    release = Event()
    calls = []

    def operation():
        calls.append("run")
        started.set()
        release.wait(timeout=3)
        return {"message": "resumed result"}

    try:
        job_id = supervisor.submit(
            "assistant-request-pause",
            operation,
            input_data={"text": "keep this"},
        )
        assert started.wait(timeout=3)
        assert supervisor.pause(job_id)["status"] == "paused"
        release.set()
        time.sleep(0.05)
        assert supervisor.get(job_id)["status"] == "paused"

        resumed = supervisor.resume(job_id)
        assert resumed["status"] in {"queued", "running", "completed"}
        job = _wait_for(supervisor, job_id, "completed")
        assert job["input"] == {"text": "keep this"}
        assert job["result"] == {"message": "resumed result"}
        assert len(calls) == 2
    finally:
        release.set()
        supervisor.shutdown()


def test_cancelled_running_job_signals_operation_cancel_event(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    supervisor = BackgroundExecutionSupervisor(store, max_workers=1)
    started = Event()
    observed_cancel = Event()

    def operation(cancel_event):
        started.set()
        while not cancel_event.is_set():
            time.sleep(0.01)
        observed_cancel.set()
        return {"message": "must not complete"}

    try:
        job_id = supervisor.submit("assistant-request-cancel-event", operation)
        assert started.wait(timeout=3)
        assert supervisor.cancel(job_id)["status"] == "cancelled"
        assert observed_cancel.wait(timeout=3)
        assert supervisor.get(job_id)["status"] == "cancelled"
    finally:
        supervisor.shutdown()


def test_resume_does_not_schedule_duplicate_while_paused_operation_is_running(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    supervisor = BackgroundExecutionSupervisor(store, max_workers=1)
    started = Event()
    release = Event()
    calls = []

    def operation():
        calls.append("run")
        started.set()
        release.wait(timeout=3)
        return {"message": "paused result"}

    try:
        job_id = supervisor.submit("assistant-request-no-duplicate-resume", operation)
        assert started.wait(timeout=3)
        assert supervisor.pause(job_id)["status"] == "paused"

        with pytest.raises(JobTransitionError):
            supervisor.resume(job_id)

        assert calls == ["run"]
        release.set()
        supervisor._futures[job_id].result(timeout=3)
        assert supervisor.get(job_id)["status"] == "paused"
        assert supervisor.resume(job_id)["status"] in {"queued", "running", "completed"}
        assert _wait_for(supervisor, job_id, "completed")["result"] == {"message": "paused result"}
        assert calls == ["run", "run"]
    finally:
        release.set()
        supervisor.shutdown()


def test_cancelled_job_cannot_be_reported_as_completed(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    supervisor = BackgroundExecutionSupervisor(store, max_workers=1)
    started = Event()
    release = Event()

    def operation():
        started.set()
        release.wait(timeout=3)
        return {"message": "must not complete"}

    try:
        job_id = supervisor.submit("assistant-request-cancel", operation)
        assert started.wait(timeout=3)
        assert supervisor.cancel(job_id)["status"] == "cancelled"
        release.set()
        time.sleep(0.05)
        assert supervisor.get(job_id)["status"] == "cancelled"
    finally:
        release.set()
        supervisor.shutdown()


def test_jobs_can_be_listed_and_failed_jobs_can_be_retried(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    supervisor = BackgroundExecutionSupervisor(store, max_workers=1)
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("try again")
        return {"ok": True}

    try:
        job_id = supervisor.submit("assistant-request-retry", operation)
        _wait_for(supervisor, job_id, "failed")
        jobs = supervisor.list_jobs(status="failed")
        assert [item["jobId"] for item in jobs] == [job_id]
        assert supervisor.retry(job_id)["status"] in {"queued", "running", "completed"}
        assert _wait_for(supervisor, job_id, "completed")["result"] == {"ok": True}
    finally:
        supervisor.shutdown()


def test_queued_job_stays_paused_until_explicit_resume(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    supervisor = BackgroundExecutionSupervisor(store, max_workers=1)
    started = Event()
    release = Event()

    def blocking_operation():
        started.set()
        release.wait(timeout=3)
        return {"id": "blocking"}

    try:
        supervisor.submit("assistant-request-blocking", blocking_operation)
        assert started.wait(timeout=3)
        queued_id = supervisor.submit("assistant-request-queued", lambda: {"id": "queued"})
        assert supervisor.pause(queued_id)["status"] == "paused"
        release.set()
        time.sleep(0.05)
        assert supervisor.get(queued_id)["status"] == "paused"
        supervisor.resume(queued_id)
        assert _wait_for(supervisor, queued_id, "completed")["result"] == {"id": "queued"}
    finally:
        release.set()
        supervisor.shutdown()


def test_paused_job_stays_paused_after_restart_until_explicit_resume(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    first = BackgroundExecutionSupervisor(store, max_workers=1)
    try:
        job_id = "assistant-job-paused-restart"
        first._create(
            job_id,
            "assistant-request-paused-restart",
            {"text": "paused"},
        )
        assert first.pause(job_id)["status"] == "paused"
    finally:
        first.shutdown(wait=False)

    second = BackgroundExecutionSupervisor(store, max_workers=1)
    try:
        assert second.resume_pending(lambda _job: lambda: {"id": "must-wait"}) == []
        assert second.get(job_id)["status"] == "paused"
        second.resume(job_id, lambda _job: lambda: {"id": "must-wait"})
        assert _wait_for(second, job_id, "completed")["result"] == {"id": "must-wait"}
    finally:
        second.shutdown()


def test_two_supervisors_cannot_resume_the_same_stale_running_job(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    first = BackgroundExecutionSupervisor(store, max_workers=1)
    second = BackgroundExecutionSupervisor(store, max_workers=1)
    job_id = "assistant-job-single-resume"
    started = Event()
    release = Event()
    try:
        first._create(job_id, "assistant-request-single-resume", {"text": "once"})
        with store._connect() as connection:
            connection.execute(
                "UPDATE assistant_jobs SET status = 'running', updated_at = ? WHERE job_id = ?",
                ("2000-01-01T00:00:00+00:00", job_id),
            )

        def operation_factory(job):
            def operation():
                started.set()
                release.wait(timeout=3)
                return {"message": job["input"]["text"]}
            return operation

        first_resumed = first.resume_pending(operation_factory)
        assert started.wait(timeout=3)
        second_resumed = second.resume_pending(operation_factory)

        assert first_resumed == [job_id]
        assert second_resumed == []
        release.set()
        assert _wait_for(first, job_id, "completed")["result"] == {"message": "once"}
    finally:
        release.set()
        first.shutdown()
        second.shutdown()

