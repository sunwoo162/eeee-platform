import json
import sys
from types import SimpleNamespace
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.api.routes import build_assistant_router
from app.main import create_app
from app.memory.store import MemoryStore
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


def test_background_route_replaces_accepted_reply_in_canonical_transcript(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    accepted = client.post(
        "/api/assistant/route",
        json={"text": "Todo 앱 만들어줘", "conversationId": "background-canonical"},
    )
    payload = wait_for_project_job(client, accepted)

    messages = client.get(
        "/v1/conversations/background-canonical/messages"
    ).json()["items"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == payload["message"]
    assert messages[1]["status"] == "failed"


def test_assistant_route_keeps_non_project_intent_out_of_project_creation(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    response = client.post("/api/assistant/route", json={"text": "내일 회의 일정 등록해줘"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["selection"]["capability_id"] == "personal-secretary"
    assert payload["project_id"] is None
    assert payload["project_profile"] is None


def test_assistant_route_reports_unavailable_presence_without_claiming_success(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    response = client.post(
        "/api/assistant/route",
        json={"text": "바탕화면 위젯으로 보여줘", "conversationId": "presence-api"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unsupported"
    assert payload["response_verification"]["decision"] == "BLOCKED"
    assert payload["message"]
    assert "완료" not in payload["message"]


def test_assistant_route_reuses_a_reminder_for_the_same_request_id(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))
    request = {
        "text": "내일 오후 3시에 팀 회의 알려줘",
        "conversationId": "reminder-idempotency",
        "requestId": "reminder-request-1",
    }

    first = client.post("/api/assistant/route", json=request)
    retry = client.post("/api/assistant/route", json=request)

    assert first.status_code == 200
    assert retry.status_code == 200
    assert first.json()["status"] == "completed"
    assert retry.json()["status"] == "completed"
    assert first.json()["reminder"]["id"] == retry.json()["reminder"]["id"]
    transcript = client.get("/api/assistant/conversations/reminder-idempotency")
    assert transcript.status_code == 200
    assert transcript.json()["messageCount"] == 2


def test_legacy_assistant_history_is_isolated_by_user_header(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))
    user_a = {"X-EEEE-User-Id": "user-a"}
    user_b = {"X-EEEE-User-Id": "user-b"}

    response = client.post(
        "/api/assistant/route",
        headers=user_a,
        json={"text": "내일 오후 3시에 팀 회의 알려줘", "conversationId": "scoped-history"},
    )

    assert response.status_code == 200
    assert client.get("/api/assistant/conversations", headers=user_a).json()
    assert client.get("/api/assistant/conversations", headers=user_b).json() == []
    assert client.get(
        "/api/assistant/conversations/scoped-history", headers=user_b
    ).status_code == 404


def test_legacy_history_fallback_keeps_user_scope(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    memory.init()
    memory.append_conversation_turn(
        "fallback-history",
        "user",
        "사용자 A의 기록",
        user_id="user-a",
    )
    service = SimpleNamespace(coordinator=SimpleNamespace(memory=memory))
    application = FastAPI()
    application.include_router(build_assistant_router(service, conversation_store=None))
    client = TestClient(application)

    user_a = client.get(
        "/api/assistant/conversations", headers={"X-EEEE-User-Id": "user-a"}
    )
    user_b = client.get(
        "/api/assistant/conversations", headers={"X-EEEE-User-Id": "user-b"}
    )

    assert [item["conversationId"] for item in user_a.json()] == ["fallback-history"]
    assert user_b.json() == []


def test_assistant_route_runs_local_document_save_and_search(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    saved = client.post(
        "/api/assistant/route",
        json={
            "text": "문서 저장해줘: 배포 체크리스트\n테스트 통과 후 배포한다.",
            "conversationId": "knowledge-api",
        },
    )
    found = client.post(
        "/api/assistant/route",
        json={"text": "문서 검색해줘: 배포", "conversationId": "knowledge-api"},
    )

    assert saved.status_code == 200
    assert saved.json()["status"] == "completed"
    assert saved.json()["document"]["title"] == "배포 체크리스트"
    assert found.status_code == 200
    assert found.json()["status"] == "completed"
    assert found.json()["documents"][0]["id"] == saved.json()["document"]["id"]
    assert found.json()["sources"][0]["contentHash"]


def test_assistant_route_does_not_cross_user_documents_with_same_conversation_id(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))
    user_a = {"X-EEEE-User-Id": "user-a"}
    user_b = {"X-EEEE-User-Id": "user-b"}

    saved = client.post(
        "/api/assistant/route",
        headers=user_a,
        json={
            "text": "문서 저장해줘: A 전용 문서\nA 사용자만 볼 수 있는 내용",
            "conversationId": "same-conversation",
        },
    )
    found = client.post(
        "/api/assistant/route",
        headers=user_b,
        json={
            "text": "문서 검색해줘: A 사용자",
            "conversationId": "same-conversation",
        },
    )

    assert saved.status_code == 200
    # The canonical conversation itself is user-owned, so another user cannot
    # even attach a request to the same conversation ID.
    assert found.status_code == 404


def test_assistant_route_returns_clarification_for_ambiguous_intent(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    response = client.post("/api/assistant/route", json={"text": "이거 해줘"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "needs_clarification"
    assert payload["project_id"] is None


def test_assistant_route_uses_builtin_fallback_when_web_is_unavailable(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
        chatgpt_web_enabled=True,
        chatgpt_web_bridge_url="http://127.0.0.1:1",
        ollama_model=None,
    )
    application = create_app(settings)
    client = TestClient(application)

    response = client.post(
        "/api/assistant/route",
        json={"text": "안녕", "conversationId": "builtin-fallback"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["provider"] == "builtin"
    assert "안녕" in payload["message"]
    transcript = application.state.conversation_store.get_transcript("builtin-fallback")
    assert [
        {"role": turn["role"], "content": turn["content"]}
        for turn in transcript["turns"]
    ] == [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": payload["message"]},
    ]
    assert application.state.coordinator.memory.recent_conversation_turns(
        "builtin-fallback"
    ) == []


def test_assistant_route_keeps_complex_request_blocked_without_provider(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
        chatgpt_web_enabled=True,
        chatgpt_web_bridge_url="http://127.0.0.1:1",
        ollama_model=None,
    )
    client = TestClient(create_app(settings))

    response = client.post(
        "/api/assistant/route",
        json={"text": "코드 작성해줘", "conversationId": "complex-fallback"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["provider"] is None
    assert payload["response_verification"]["decision"] == "BLOCKED"


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


def test_assistant_route_uses_the_request_user_plugin_connection(tmp_path) -> None:
    application = create_app(Settings(
        data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces",
        claim_latch_auto_start=False,
    ))
    application.state.plugin_platform.credentials = MemoryCredentialStore()
    application.state.plugin_platform.connectors = {"gmail": _RouteGmailConnector()}
    application.state.plugin_platform.install("gmail")
    application.state.plugin_platform.connect(
        "user-a", "gmail", {"mail.read"}, {"access_token": "secret"}, "Work"
    )
    client = TestClient(application)

    response = client.post(
        "/api/assistant/route",
        json={"text": "안 읽은 메일 5개 보여줘"},
        headers={"X-EEEE-User-Id": "user-a"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["plugin_id"] == "gmail"


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


def test_forged_assistant_approval_without_server_request_does_not_send(tmp_path) -> None:
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
        {"access_token": "secret"}, "Work"
    )
    client = TestClient(application)

    response = client.post(
        "/api/assistant/route",
        json={"text": "s25011@gsm.hs.kr 에 test라는 메일 보내", "approved": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert response.json()["approvalRequired"] is True
    assert connector.invoke_count == 0


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
