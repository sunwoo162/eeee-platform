from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_chat_history_plugin_can_list_and_page_persistent_eeee_conversation(tmp_path) -> None:
    application = create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    )
    memory = application.state.coordinator.memory
    memory.append_conversation_turn("desktop-default", "user", "오늘 일정 정리해줘")
    memory.append_conversation_turn("desktop-default", "assistant", "정리할게.")
    memory.append_conversation_turn("desktop-default", "user", "그리고 우선순위도 붙여줘")

    with TestClient(application) as client:
        conversations = client.get("/api/assistant/conversations").json()
        page = client.get(
            "/api/assistant/conversations/desktop-default",
            params={"limit": 2},
        )

    assert conversations[0]["conversationId"] == "desktop-default"
    assert conversations[0]["messageCount"] == 3
    assert conversations[0]["preview"] == "그리고 우선순위도 붙여줘"
    assert page.status_code == 200
    assert [turn["role"] for turn in page.json()["turns"]] == ["assistant", "user"]
    assert page.json()["turns"][0]["content"] == "정리할게."


def test_chat_history_plugin_rejects_invalid_history_cursor(tmp_path) -> None:
    application = create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    )

    with TestClient(application) as client:
        response = client.get(
            "/api/assistant/conversations/desktop-default",
            params={"beforeId": 0},
        )

    assert response.status_code == 422
