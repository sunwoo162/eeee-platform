from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_legacy_assistant_route_projects_terminal_request_and_events(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    client = TestClient(create_app(settings))

    response = client.post(
        "/api/assistant/route",
        json={
            "text": "안녕",
            "conversationId": "route-lifecycle",
            "requestId": "assistant-request-lifecycle-1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["requestId"] == "assistant-request-lifecycle-1"
    request = client.app.state.conversation_store.get_request(payload["requestId"])
    assert request.state.value == "completed"
    transcript = client.app.state.conversation_store.get_transcript("route-lifecycle")
    assistant_turn = transcript["turns"][-1]
    assert assistant_turn["role"] == "assistant"
    assert assistant_turn["provider"] == "builtin"
    assert assistant_turn["errorCode"] is None
    events = client.app.state.conversation_store.events_after(request.id)
    assert [event.event_type for event in events] == [
        "request.accepted",
        "request.classified",
        "request.executing",
        "request.completed",
    ]


def test_legacy_assistant_route_projects_blocked_result_as_failed_request(tmp_path):
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
        json={
            "text": "코드 작성해줘",
            "conversationId": "route-lifecycle-blocked",
            "requestId": "assistant-request-lifecycle-2",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    request = client.app.state.conversation_store.get_request(
        "assistant-request-lifecycle-2"
    )
    assert request.state.value == "failed"
    assert request.error_code == "assistant_route_failed"
