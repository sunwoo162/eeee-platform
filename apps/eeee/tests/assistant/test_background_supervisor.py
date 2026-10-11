import time

from app.assistant.background import BackgroundExecutionSupervisor
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


def test_pending_job_can_be_resumed_by_a_new_supervisor(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    first = BackgroundExecutionSupervisor(store, max_workers=1)
    job_id = first.submit(
        "assistant-request-recover",
        lambda: {"message": "will be recovered"},
        input_data={"text": "resume me"},
    )
    first.shutdown(wait=False)

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

