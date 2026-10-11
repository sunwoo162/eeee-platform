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

