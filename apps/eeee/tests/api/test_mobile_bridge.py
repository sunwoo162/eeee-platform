from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


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
    kinds = [event["kind"] for event in events.json()["events"]]
    assert "assistant.route.started" in kinds
    assert kinds[-1] == "assistant.route.completed"
    assert events.json()["events"][-1]["payload"]["deviceId"] == paired.json()["deviceId"]


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
