from fastapi.testclient import TestClient
import time

from app.config import Settings
from app.main import create_app


def test_one_sentence_todo_request_creates_project_and_map(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    with TestClient(create_app(settings)) as client:
        routed = client.post("/api/assistant/route", json={"text": "Todo 앱 만들어줘"})

        assert routed.status_code == 200, routed.text
        accepted = routed.json()
        assert accepted["status"] == "accepted", accepted
        deadline = time.monotonic() + 10
        job = None
        while time.monotonic() < deadline:
            job = client.get(f"/api/assistant/jobs/{accepted['jobId']}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert job and job["status"] == "completed", job
        payload = job["result"]
        assert payload["project_id"]

        snapshot = client.get(f"/api/projects/{payload['project_id']}/map")
        assert snapshot.status_code == 200
        assert snapshot.json()["projectId"] == payload["project_id"]
        assert snapshot.json()["nodes"]
