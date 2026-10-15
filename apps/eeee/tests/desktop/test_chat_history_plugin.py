import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel

from plugins.eeee_chat_history.window import ChatHistoryWindow


def _settle() -> None:
    app = QApplication.instance()
    deadline = time.time() + 1.5
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)
    app.processEvents()


class ChatHistoryClient:
    base_url = "http://127.0.0.1:8123"

    def __init__(self):
        self.sent = []

    def get_conversations(self, *, limit=50):
        return [{
            "conversationId": "desktop-default",
            "messageCount": 2,
            "preview": "Ollama 답변",
            "updatedAt": "2026-10-15T00:00:00+00:00",
        }]

    def get_conversation(self, conversation_id="desktop-default", *, limit=100, before_id=None):
        assert conversation_id == "desktop-default"
        return {
            "conversationId": conversation_id,
            "turns": [
                {"id": 1, "role": "user", "content": "첫 명령", "createdAt": "now"},
                {"id": 2, "role": "assistant", "content": "Ollama 답변", "createdAt": "now"},
            ],
            "nextBeforeId": None,
        }

    def send_conversation_message(self, text, *, conversation_id="desktop-default", workspace=None):
        self.sent.append((text, conversation_id))
        return {"status": "completed", "message": "새 답변"}


def test_chat_history_plugin_renders_persistent_turns_and_sends_back_to_eeee():
    app = QApplication.instance() or QApplication([])
    client = ChatHistoryClient()
    window = ChatHistoryWindow(client)
    _settle()

    labels = [label.text() for label in window.transcript.findChildren(QLabel)]
    assert "첫 명령" in labels
    assert "Ollama 답변" in labels

    window.input.setText("다음 명령")
    window._send()
    _settle()

    assert client.sent == [("다음 명령", "desktop-default")]
    assert "2개 메시지" in window.status.text()
    window.close()
