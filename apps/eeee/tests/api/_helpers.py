from __future__ import annotations

import time


def wait_for_project_job(client, response, *, timeout: float = 10.0) -> dict:
    """Resolve the accepted assistant request into its durable terminal result."""
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
