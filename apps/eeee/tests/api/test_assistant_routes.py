import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

FIXTURES = Path(__file__).parents[1] / "plugins" / "fixtures"


def test_assistant_route_exposes_one_project_runtime_profile(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    response = client.post("/api/assistant/route", json={"text": "웹 프로젝트 하나 만들어줘"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["selection"]["capability_id"] == "project-execution"
    assert payload["project_id"]
    assert payload["project_profile"]["projectId"] == payload["project_id"]
    assert payload["status"] == "awaiting_configuration"
    assert "notion" in payload["missing_connectors"]
    assert "google-calendar" in payload["missing_connectors"]

    profile_response = client.get(f"/api/projects/{payload['project_id']}/profile")

    assert profile_response.status_code == 200
    assert profile_response.json()["projectId"] == payload["project_id"]


def test_assistant_route_keeps_non_project_intent_out_of_project_creation(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    response = client.post("/api/assistant/route", json={"text": "내일 회의 일정 등록해줘"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["selection"]["capability_id"] == "personal-secretary"
    assert payload["project_id"] is None
    assert payload["project_profile"] is None


def test_assistant_route_returns_clarification_for_ambiguous_intent(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    response = client.post("/api/assistant/route", json={"text": "이거 해줘"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "needs_clarification"
    assert payload["project_id"] is None


def test_assistant_route_reports_missing_optional_plugin_without_creating_project(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    response = client.post("/api/assistant/route", json={"text": "노션에 회의록 저장해줘"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "plugin_required"
    assert payload["required_plugin_id"] == "notion"
    assert payload["required_plugin_name"] == "Notion"
    assert payload["required_plugin_permissions"]
    assert payload["suggested_action"]
    assert payload["project_id"] is None


def test_project_document_sync_reports_missing_notion_configuration(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    created = client.post("/api/assistant/route", json={"text": "웹 프로젝트 하나 만들어줘"})
    project_id = created.json()["project_id"]
    response = client.post(f"/api/projects/{project_id}/documents/sync")

    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_configuration"


def test_connected_plugin_capability_runs_through_eeee_and_keeps_verification(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))
    manifest = json.loads((FIXTURES / "echo-plugin.json").read_text(encoding="utf-8"))
    manifest["command"] = [sys.executable, str(FIXTURES / "echo_plugin.py")]
    manifest["capabilities"] = [{
        "id": "echo-search",
        "displayName": "Echo Search",
        "intents": ["search"],
        "triggerPhrases": ["echo search"],
        "actionId": "echo",
        "permissionIds": ["local.read"],
        "sideEffectLevel": "none",
        "approvalLevel": "none",
    }]
    assert client.post("/api/plugins/echo/register", json=manifest).status_code == 200
    assert client.post("/api/plugins/echo/connect", json={"approved": True}).status_code == 200

    response = client.post("/api/assistant/route", json={"text": "echo search"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["selection"]["capability_id"] == "plugin:echo:echo-search"
    assert payload["status"] == "completed"
    assert payload["plugin_id"] == "echo"
    assert payload["plugin_execution_id"]
    assert payload["response_verification"]["profile_version"] == "claimlatch-v0.2.0"
