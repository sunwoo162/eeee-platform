from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.project_runtime.models import ProjectProfile


def test_mobile_controls_desktop_owned_assistant_and_receives_live_events(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    assert client.get("/api/mobile/state").status_code == 401

    pairing = client.post("/api/bridge/pairing/code")
    assert pairing.status_code == 200
    paired = client.post(
        "/api/mobile/pair",
        json={"pairingCode": pairing.json()["code"], "deviceName": "My phone"},
    )
    assert paired.status_code == 200
    token = paired.json()["accessToken"]
    headers = {"X-Gleave-Bridge-Token": token}

    state = client.get("/api/mobile/state", headers=headers)
    assert state.status_code == 200
    assert state.json()["transport"] == "desktop-bridge"
    assert state.json()["bridge"]["realtime"] == "sse-or-polling"

    command = client.post(
        "/api/mobile/assistant/route",
        headers=headers,
        json={"text": "내일 오후 3시에 회의 일정 등록해줘"},
    )
    assert command.status_code == 200
    assert command.json()["selection"]["capability_id"] == "personal-secretary"

    events = client.get("/api/mobile/events", headers=headers)
    assert events.status_code == 200
    assert events.json()["hasGap"] is False
    assert events.json()["oldestCursor"] is not None
    kinds = [event["kind"] for event in events.json()["events"]]
    assert "assistant.route.started" in kinds
    assert kinds[-1] == "assistant.route.completed"
    assert events.json()["events"][-1]["payload"]["deviceId"] == paired.json()["deviceId"]
    assert events.json()["events"][-1]["payload"]["conversationId"] == "desktop-default"
    assert events.json()["events"][-1]["payload"]["requestId"] == command.json()["requestId"]


def test_mobile_accepted_route_publishes_accepted_event_not_completed(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))
    pairing = client.post("/api/bridge/pairing/code").json()
    token = client.post(
        "/api/mobile/pair",
        json={"pairingCode": pairing["code"], "deviceName": "Accepted event test"},
    ).json()["accessToken"]
    headers = {"X-Gleave-Bridge-Token": token}

    command = client.post(
        "/api/mobile/assistant/route",
        headers=headers,
        json={
            "text": "Todo 앱 만들어줘",
            "conversationId": "mobile-accepted-event",
            "requestId": "mobile-accepted-event-1",
        },
    )
    assert command.status_code == 200
    assert command.json()["status"] == "accepted"

    events = client.get("/api/mobile/events", headers=headers).json()["events"]
    accepted_events = [event for event in events if event["payload"].get("status") == "accepted"]
    assert accepted_events
    assert accepted_events[-1]["kind"] == "assistant.route.accepted"
    assert not any(
        event["kind"] == "assistant.route.completed"
        and event["payload"].get("status") == "accepted"
        for event in events
    )


def test_mobile_can_read_authenticated_canonical_conversation_history(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))
    pairing = client.post("/api/bridge/pairing/code").json()
    token = client.post(
        "/api/mobile/pair",
        json={"pairingCode": pairing["code"], "deviceName": "History test"},
    ).json()["accessToken"]
    headers = {"X-Gleave-Bridge-Token": token}
    conversation_id = "mobile-history"

    assert client.get("/api/mobile/assistant/conversations").status_code == 401
    command = client.post(
        "/api/mobile/assistant/route",
        headers=headers,
        json={
            "text": "내일 오후 3시에 회의 일정 등록해줘",
            "conversationId": conversation_id,
            "requestId": "mobile-history-1",
        },
    )
    assert command.status_code == 200

    conversations = client.get(
        "/api/mobile/assistant/conversations", headers=headers
    )
    assert conversations.status_code == 200
    assert any(
        item["conversationId"] == conversation_id for item in conversations.json()
    )
    page = client.get(
        "/api/mobile/assistant/conversations",
        headers=headers,
        params={
            "beforeUpdatedAt": conversations.json()[0]["updatedAt"],
            "beforeConversationId": conversations.json()[0]["conversationId"],
        },
    )
    assert page.status_code == 200
    assert page.json() == []

    messages = client.get(
        f"/api/mobile/assistant/conversations/{conversation_id}/messages",
        headers=headers,
    )
    assert messages.status_code == 200
    payload = messages.json()
    assert payload["conversationId"] == conversation_id
    assert [turn["role"] for turn in payload["turns"]] == ["user", "assistant"]
    assert payload["turns"][0]["requestId"] == "mobile-history-1"


def test_mobile_token_survives_desktop_restart(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    first = TestClient(create_app(settings))
    pairing = first.post("/api/bridge/pairing/code").json()
    token = first.post(
        "/api/mobile/pair",
        json={"pairingCode": pairing["code"], "deviceName": "Restart test"},
    ).json()["accessToken"]

    second = TestClient(create_app(settings))
    response = second.get(
        "/api/mobile/state",
        headers={"X-Gleave-Bridge-Token": token},
    )

    assert response.status_code == 200
    assert response.json()["bridge"]["pairedDevices"] == 1


def test_mobile_history_is_isolated_by_the_user_bound_to_the_pairing_code(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    pairing_a = client.post(
        "/api/desktop/pairing/code", headers={"X-EEEE-User-Id": "user-a"}
    ).json()
    token_a = client.post(
        "/api/mobile/pair",
        json={"pairingCode": pairing_a["code"], "deviceName": "User A phone"},
    ).json()["accessToken"]
    pairing_b = client.post(
        "/api/desktop/pairing/code", headers={"X-EEEE-User-Id": "user-b"}
    ).json()
    token_b = client.post(
        "/api/mobile/pair",
        json={"pairingCode": pairing_b["code"], "deviceName": "User B phone"},
    ).json()["accessToken"]

    created = client.post(
        "/api/mobile/assistant/route",
        headers={"X-Gleave-Bridge-Token": token_a},
        json={
            "text": "내일 오후 3시에 사용자 A 회의 일정 등록해줘",
            "conversationId": "same-mobile-conversation",
        },
    )
    assert created.status_code == 200

    hidden = client.get(
        "/api/mobile/assistant/conversations",
        headers={"X-Gleave-Bridge-Token": token_b},
    )
    visible = client.get(
        "/api/mobile/assistant/conversations",
        headers={"X-Gleave-Bridge-Token": token_a},
    )

    assert hidden.status_code == 200
    assert visible.status_code == 200
    assert hidden.json() == []
    assert any(
        item["conversationId"] == "same-mobile-conversation"
        for item in visible.json()
    )


def test_mobile_project_state_is_isolated_by_the_pairing_user(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))
    project = client.app.state.coordinator.create_project(
        "mobile-private-project",
        "User A project",
        str(tmp_path / "workspaces" / "mobile-private-project"),
        user_id="user-a",
    )
    client.app.state.coordinator.store.save_project_profile(ProjectProfile(
        project_id=project.id,
        project_revision=project.revision,
        goal="User A project",
        workspace=project.workspace,
        capabilities=["project-execution"],
    ))

    pairing_a = client.post(
        "/api/desktop/pairing/code", headers={"X-EEEE-User-Id": "user-a"}
    ).json()
    token_a = client.post(
        "/api/mobile/pair",
        json={"pairingCode": pairing_a["code"], "deviceName": "User A phone"},
    ).json()["accessToken"]
    pairing_b = client.post(
        "/api/desktop/pairing/code", headers={"X-EEEE-User-Id": "user-b"}
    ).json()
    token_b = client.post(
        "/api/mobile/pair",
        json={"pairingCode": pairing_b["code"], "deviceName": "User B phone"},
    ).json()["accessToken"]

    visible = client.get(
        "/api/mobile/state",
        params={"projectId": project.id},
        headers={"X-Gleave-Bridge-Token": token_a},
    )
    hidden = client.get(
        "/api/mobile/state",
        params={"projectId": project.id},
        headers={"X-Gleave-Bridge-Token": token_b},
    )

    assert visible.status_code == 200
    assert visible.json()["projectId"] == project.id
    assert hidden.status_code == 404
