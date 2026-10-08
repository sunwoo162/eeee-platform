from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_user_can_request_todo_and_receive_a_generated_project(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    with TestClient(create_app(settings)) as client:
        response = client.post("/api/assistant/route", json={"text": "Todo 앱 만들어줘"})

        assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["project_profile"], payload
    workspace = Path(payload["project_profile"]["workspace"])
    assert payload["selection"]["capability_id"] == "project-execution"
    assert payload["status"] == "completed", payload
    assert payload["qualityStatus"] == "PASS", payload
    assert payload["qaReportPath"].endswith("QA_REPORT.json")
    assert payload["releaseManifestPath"].endswith("RELEASE_MANIFEST.json")
    assert payload["response_verification"]["profile_version"] == "claimlatch-v0.2.0"
    assert payload["gitBranch"].startswith("project/")
    assert len(payload["gitCommit"]) == 40
    assert payload["executionPlanPath"].endswith("execution-plan.json")
    assert (workspace / "index.html").is_file()
    assert (workspace / "src" / "entities" / "todo" / "model.js").is_file()
    assert (workspace / "README.md").is_file()
    assert (workspace / "execution-plan.json").is_file()
    assert (workspace / "PROJECT_PROFILE.json").is_file()
    assert (workspace / "PROJECT_LOG.md").is_file()


def test_user_can_request_a_login_web_todo_and_receive_a_full_stack_project(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    with TestClient(create_app(settings)) as client:
        response = client.post("/api/assistant/route", json={"text": "로그인 기능이 있는 Todo 웹앱 만들어줘"})

    payload = response.json()
    workspace = Path(payload["project_profile"]["workspace"])
    assert response.status_code == 200, response.text
    assert payload["project_profile"]["runtimeProfile"] == "web_app"
    assert payload["qualityStatus"] == "PASS", payload
    assert (workspace / "apps" / "web" / "index.html").is_file()
    assert (workspace / "apps" / "api" / "server.py").is_file()
    assert any(item["state"] == "awaiting_configuration" for item in payload["project_profile"]["connectors"])
