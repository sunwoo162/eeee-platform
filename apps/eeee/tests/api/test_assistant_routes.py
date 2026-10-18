import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plugins.connectors import ConnectorConnection, ConnectorHealth
from app.plugins.credentials import MemoryCredentialStore
from tests.api._helpers import wait_for_project_job

FIXTURES = Path(__file__).parents[1] / "plugins" / "fixtures"


def test_assistant_route_exposes_one_project_runtime_profile(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    response = client.post("/api/assistant/route", json={"text": "웹 프로젝트 하나 만들어줘"})

    assert response.status_code == 200
    payload = wait_for_project_job(client, response)
    assert payload["selection"]["capability_id"] == "project-execution"
    assert payload["project_id"]
    assert payload["project_profile"]["project_id"] == payload["project_id"]
    assert payload["status"] == "blocked"
    # Without a configured execution runtime, the truthful terminal state is
    # blocked and no external connector claim is emitted.
    assert payload["missing_connectors"] == []

    profile_response = client.get(f"/api/projects/{payload['project_id']}/profile")

    assert profile_response.status_code == 200
    assert profile_response.json()["projectId"] == payload["project_id"]


def test_assistant_result_exposes_final_quality_fields_after_background_completion(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    accepted = client.post("/api/assistant/route", json={"text": "Todo 앱 만들어줘"})
    payload = wait_for_project_job(client, accepted)

    assert "final_report_path" in payload
    assert payload["final_report_path"].endswith("FINAL-QUALITY-REPORT.json")
    assert payload["quality_grade"] in {"replan_required", "revision_required", "client_ready_with_notes", "portfolio_ready"}
    assert isinstance(payload["quality_score"], int)
    assert isinstance(payload["missing_extensions"], list)


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
    project_id = wait_for_project_job(client, created)["project_id"]
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


class _RouteGmailConnector:
    plugin_id = "gmail"

    def connect(self, user_id, credential, approved_permissions):
        return ConnectorConnection(
            user_id=user_id,
            plugin_id=self.plugin_id,
            approved_permissions=frozenset(approved_permissions),
            client=object(),
        )

    def disconnect(self, connection):
        return None

    def health(self, connection):
        return ConnectorHealth(status="healthy", code="healthy", reason="ok")

    def invoke(self, connection, action, value):
        return {"action": action, "input": value}


class _CountingRouteGmailConnector(_RouteGmailConnector):
    def __init__(self):
        self.invoke_count = 0

    def invoke(self, connection, action, value):
        self.invoke_count += 1
        return super().invoke(connection, action, value)


def test_connected_gmail_is_selected_and_receives_normalized_natural_language_input(tmp_path) -> None:
    application = create_app(Settings(
        data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces",
        claim_latch_auto_start=False,
    ))
    application.state.plugin_platform.credentials = MemoryCredentialStore()
    application.state.plugin_platform.connectors = {"gmail": _RouteGmailConnector()}
    application.state.plugin_platform.install("gmail")
    application.state.plugin_platform.connect(
        "local-user", "gmail", {"mail.read"}, {"access_token": "secret"}, "Work"
    )
    client = TestClient(application)

    response = client.post("/api/assistant/route", json={"text": "안 읽은 메일 5개 보여줘"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["selection"]["capability_id"] == "plugin:gmail:mail.list"
    assert payload["plugin_id"] == "gmail"
    assert payload["pluginOutput"]["action"] == "mail.list"
    assert payload["pluginOutput"]["input"]["query"] == "is:unread"
    assert payload["pluginOutput"]["input"]["limit"] == 5


def test_natural_language_gmail_send_is_waiting_for_action_approval(tmp_path) -> None:
    application = create_app(Settings(
        data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces",
        claim_latch_auto_start=False,
    ))
    application.state.plugin_platform.credentials = MemoryCredentialStore()
    application.state.plugin_platform.connectors = {"gmail": _RouteGmailConnector()}
    application.state.plugin_platform.install("gmail")
    application.state.plugin_platform.connect(
        "local-user", "gmail", {"mail.read", "mail.send"},
        {"access_token": "secret"}, "Work"
    )
    client = TestClient(application)

    response = client.post(
        "/api/assistant/route",
        json={"text": "s25011@gsm.hs.kr 에 test라는 메일 보내"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selection"]["capability_id"] == "plugin:gmail:mail.send"
    assert payload["status"] == "blocked"
    assert "승인" in payload["message"]
    assert payload["approvalRequired"] is True
    assert payload["approvalCapabilityId"] == "plugin:gmail:mail.send"
    assert payload["approvalPluginId"] == "gmail"
    assert payload["approvalSideEffectLevel"] == "external"
    assert payload["approvalRequestId"]


def test_approved_plugin_request_reuses_the_same_execution_when_submitted_twice(tmp_path) -> None:
    connector = _CountingRouteGmailConnector()
    application = create_app(Settings(
        data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces",
        claim_latch_auto_start=False,
    ))
    application.state.plugin_platform.credentials = MemoryCredentialStore()
    application.state.plugin_platform.connectors = {"gmail": connector}
    application.state.plugin_platform.install("gmail")
    application.state.plugin_platform.connect(
        "local-user", "gmail", {"mail.read", "mail.send"},
        {"access_token": "secret"}, "Work",
    )
    client = TestClient(application)
    text = "s25011@gsm.hs.kr 에 test라는 메일 보내"

    waiting = client.post("/api/assistant/route", json={"text": text}).json()
    approval_request_id = waiting["approvalRequestId"]
    first = client.post(
        "/api/assistant/route",
        json={
            "text": text,
            "approved": True,
            "approvalRequestId": approval_request_id,
        },
    )
    second = client.post(
        "/api/assistant/route",
        json={
            "text": text,
            "approved": True,
            "approvalRequestId": approval_request_id,
        },
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["plugin_id"] == "gmail"
    assert first_payload["status"] == "completed"
    assert second_payload["status"] == "completed"
    assert first_payload["plugin_execution_id"] == second_payload["plugin_execution_id"]
    assert connector.invoke_count == 1

    desktop_state = client.get("/api/desktop/state").json()
    assert desktop_state["pluginExecutions"][0]["pluginId"] == "gmail"
    assert desktop_state["pluginExecutions"][0]["status"] == "completed"
