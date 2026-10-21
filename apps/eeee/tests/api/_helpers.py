from __future__ import annotations

import time


def wait_for_project_job(client, response, *, timeout: float = 60.0) -> dict:
    """Resolve the accepted assistant request into its durable terminal result.

    The local ISEOL bridge may spend up to its 30-second planner timeout before
    falling back to the native compiler. Keep the test window above that
    bounded fallback path so a valid terminal result is not reported as a
    false timeout.
    """
    payload = response.json()
    assert payload["status"] == "accepted", payload
    job_id = payload["jobId"]
    deadline = time.monotonic() + timeout
    job = None
    while time.monotonic() < deadline:
        job = client.get(f"/api/assistant/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.02)
    assert job is not None and job["status"] == "completed", job
    assert job["result"], job
    return job["result"]
