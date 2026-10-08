import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_project_request_survives_app_restart_with_truthful_connector_states(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
    )

    first_app = create_app(settings)
    with TestClient(first_app) as client:
        created = client.post(
            "/api/assistant/route",
            json={"text": "로컬 우선 웹 프로젝트 하나 만들어줘"},
        )

        assert created.status_code == 200, created.text
        payload = created.json()
        project_id = payload["project_id"]
        profile = payload["project_profile"]
        assert payload["selection"]["capability_id"] == "project-execution"
        assert payload["planningSessionId"], payload
        assert payload["planningHandoffId"], payload
        execution_plan = Path(payload["executionPlanPath"])
        assert execution_plan.is_file()
        assert json.loads(execution_plan.read_text(encoding="utf-8"))["planningHandoff"]["approval"]["status"] == "approved"
        assert profile["projectId"] == project_id
        assert profile["connectors"]
        states = {item["connectorId"]: item["state"] for item in profile["connectors"]}
        assert states["iseol-runtime"] == "ready"
        assert states["desktop"] == "ready"
        assert states["mobile-bridge"] == "ready"
        assert states["notion"] == "awaiting_configuration"
        assert states["github"] == "awaiting_configuration"
        assert states["google-calendar"] == "awaiting_configuration"
        assert all(state != "completed" for state in states.values())

    second_app = create_app(settings)
    with TestClient(second_app) as client:
        restored = client.get(f"/api/projects/{project_id}/profile")

        assert restored.status_code == 200
        assert restored.json() == profile


def test_portfolio_request_uses_existing_project_and_writes_evidence_backed_documents(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/assistant/route", json={"text": "Todo 앱 만들어줘"})
        assert created.status_code == 200, created.text
        project_id = created.json()["project_id"]
        workspace = Path(created.json()["project_profile"]["workspace"])

        portfolio = client.post(
            "/api/assistant/route",
            json={"text": "이 프로젝트 포트폴리오로 정리해줘", "projectId": project_id},
        )

        assert portfolio.status_code == 200, portfolio.text
        payload = portfolio.json()
        assert payload["selection"]["capability_id"] == "portfolio-generation"
        assert payload["project_id"] == project_id
        assert payload["status"] == "completed"
        assert payload["response_verification"]["decision"] in {"PASS", "WARN"}
        assert {Path(item["path"]).name for item in payload["portfolioArtifacts"]} == {
            "PORTFOLIO.md", "TECHNICAL_RETROSPECTIVE.md", "RESUME_SUMMARY.md", "INTERVIEW_ANSWERS.md",
        }
        assert "QA_REPORT.json" in payload["portfolioSourcePaths"]
        assert "ClaimLatch" in (workspace / "PORTFOLIO.md").read_text(encoding="utf-8")


def test_portfolio_request_without_project_does_not_create_one(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/assistant/route", json={"text": "이 프로젝트 포트폴리오로 정리해줘"})

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "blocked"
        assert payload["project_id"] is None
        assert "기존 프로젝트" in payload["message"]
