from threading import Event

from fastapi.testclient import TestClient

from app.main import create_app
from app.config import Settings


def test_assistant_job_status_is_available_from_desktop_api(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    application = create_app(settings)
    with TestClient(application) as client:
        job_id = application.state.assistant_supervisor.submit(
            "assistant-request-api", lambda: {"status": "accepted"}
        )
        response = client.get(f"/api/assistant/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["requestId"] == "assistant-request-api"
    assert response.json()["status"] in {"queued", "running", "completed"}


def test_assistant_jobs_can_be_listed_and_completed_job_cannot_be_cancelled(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    application = create_app(settings)
    with TestClient(application) as client:
        job_id = application.state.assistant_supervisor.submit(
            "assistant-request-api-list", lambda: {"status": "accepted"}
        )
        listed = client.get("/api/assistant/jobs?status=completed")
        assert listed.status_code == 200
        assert isinstance(listed.json(), list)

        for _ in range(100):
            status = client.get(f"/api/assistant/jobs/{job_id}").json()["status"]
            if status == "completed":
                break
        response = client.post(f"/api/assistant/jobs/{job_id}/cancel")

    assert response.status_code == 409
    assert "completed" in response.json()["detail"]


def test_assistant_job_controls_are_local_desktop_only(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    application = create_app(settings)
    with TestClient(
        application,
        base_url="http://desktop.example",
        client=("203.0.113.10", 1234),
    ) as client:
        response = client.get("/api/assistant/jobs")

    assert response.status_code == 403


def test_assistant_jobs_are_isolated_by_user_header(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    application = create_app(settings)
    release = Event()
    user_a = {"X-EEEE-User-Id": "user-a"}
    user_b = {"X-EEEE-User-Id": "user-b"}

    def blocking_operation():
        release.wait(timeout=3)
        return {"status": "accepted"}

    try:
        with TestClient(application) as client:
            job_id = application.state.assistant_supervisor.submit(
                "assistant-request-user-scope",
                blocking_operation,
                input_data={"userId": "user-a"},
            )

            assert client.get("/api/assistant/jobs", headers=user_a).json()[0]["jobId"] == job_id
            assert client.get("/api/assistant/jobs", headers=user_b).json() == []
            assert client.get(f"/api/assistant/jobs/{job_id}", headers=user_b).status_code == 404
            assert client.post(
                f"/api/assistant/jobs/{job_id}/cancel", headers=user_b
            ).status_code == 404
            assert client.post(
                f"/api/assistant/jobs/{job_id}/cancel", headers=user_a
            ).status_code == 200
    finally:
        release.set()

