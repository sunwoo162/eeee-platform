import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.desktop.chat_window import AssistantChatWindow


class FakeClient:
    def route_assistant(self, text, workspace=None, *, background=False):
        return {"status": "ready", "message": f"접수: {text}"}


def test_assistant_chat_window_is_a_small_command_surface():
    app = QApplication.instance() or QApplication([])
    window = AssistantChatWindow(FakeClient())
    try:
        assert window.windowTitle() == "EEEE"
        assert window.input.placeholderText() == "예: Todo 앱 만들어줘"
        assert window.send.text() == "보내기"
        assert window.width() == 420
    finally:
        window.close()
        app.processEvents()


class ConversationClient:
    def __init__(self):
        self.thread_ids = []

    def create_conversation(self, title="새 대화"):
        self.thread_ids.append(threading.get_ident())
        return {"id": "conversation-1", "title": title}

    def submit_turn(self, conversation_id, content, client_message_id):
        self.thread_ids.append(threading.get_ident())
        return {"requestId": "request-1", "state": "persisted_user_message"}

    def stream_request_events(self, request_id):
        self.thread_ids.append(threading.get_ident())
        return iter(
            [
                {"eventType": "message.started", "payload": {"messageId": "message-1"}},
                {"eventType": "message.delta", "payload": {"delta": "완료"}},
                {"eventType": "message.completed", "payload": {"content": "완료"}},
            ]
        )


class FailingConversationClient(ConversationClient):
    def submit_turn(self, conversation_id, content, client_message_id):
        raise RuntimeError("Core offline")


def _wait_for(app, predicate):
    from PySide6.QtCore import QEventLoop
    import time

    deadline = time.monotonic() + 2
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.01)


def test_answer_click_starts_fresh_input_and_long_text_changes_bubble_height():
    app = QApplication.instance() or QApplication([])
    window = AssistantChatWindow(ConversationClient())
    window.show()
    try:
        window.input.setText("한 줄 요청")
        window.submit()
        # The worker updates the session before Qt delivers the success
        # callback. Wait for the user-visible bubble instead of observing the
        # background state directly, otherwise the assertion races the render.
        _wait_for(app, lambda: window.status.text() == "완료")
        assert window.status.text() == "완료"
        answer_height = window.status.height()

        window._bubble_clicked()
        assert window.session.state == "input"
        assert window._hide_timer.isActive()
        window.input.setText("새 요청")
        assert not window._hide_timer.isActive()

        window._show_bubble("\n".join(f"{index}번째 긴 답변" for index in range(10)))
        assert window.status.height() > answer_height
    finally:
        window.close()
        app.processEvents()


def test_conversation_events_are_applied_on_the_qt_thread():
    app = QApplication.instance() or QApplication([])
    client = ConversationClient()
    window = AssistantChatWindow(client)
    apply_threads = []
    original_apply_events = window.session.apply_events

    def record_apply_events(request, events):
        apply_threads.append(threading.get_ident())
        return original_apply_events(request, events)

    window.session.apply_events = record_apply_events
    window.show()
    try:
        window.input.setText("한 줄 요청")
        window.submit()
        _wait_for(app, lambda: window.status.text() == "완료")

        assert apply_threads == [threading.get_ident()]
        assert client.thread_ids
        assert all(thread_id != threading.get_ident() for thread_id in client.thread_ids)
        assert window.session.state == "answer"
    finally:
        window.close()
        app.processEvents()


def test_conversation_failure_marks_session_error_and_restores_draft():
    app = QApplication.instance() or QApplication([])
    window = AssistantChatWindow(FailingConversationClient())
    window.show()
    try:
        window.input.setText("다시 시도해야 해")
        window.submit()
        _wait_for(app, lambda: window.session.state == "error")

        assert window.session.state == "error"
        assert window.session.draft == "다시 시도해야 해"
        assert window.input.text() == "다시 시도해야 해"
        assert window.send.isEnabled()
        assert window.input.isEnabled()
    finally:
        window.close()
        app.processEvents()
