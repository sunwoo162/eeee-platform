import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_project_request_is_accepted_before_specialist_execution_finishes(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    application = create_app(settings)
    with TestClient(application) as client:
        started = time.monotonic()
        response = client.post("/api/assistant/route", json={"text": "Todo 앱 만들어줘"})
        elapsed = time.monotonic() - started

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "accepted"
        assert payload["jobId"]
        assert elapsed < 1.0

        deadline = time.monotonic() + 5
        job = None
        while time.monotonic() < deadline:
            job = client.get(f"/api/assistant/jobs/{payload['jobId']}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert job is not None
        assert job["status"] in {"completed", "failed"}

