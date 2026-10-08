import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from app.desktop.window import PetWindow


class SlowClient:
    def get_state(self):
        return {"state": "idle", "message": "Ready for a development request"}

    def create_request(self, text):
        time.sleep(0.15)
        return {
            "state": "researching",
            "task_id": "task-1",
            "request_id": "request-1",
            "message": f"Researching {text}",
        }

    def run(self, task_id):
        time.sleep(0.15)
        return {
            "state": "awaiting_approval",
            "task_id": task_id,
            "request_id": "request-1",
            "message": "Choose a repository",
            "candidates": [],
        }


class RouteClient(SlowClient):
    def __init__(self):
        self.routed_text = None

    def get_desktop_state(self, project_id=None):
        return {"state": "idle", "message": "Ready for a development request"}

    def route_assistant(self, text, workspace=None):
        self.routed_text = text
        return {"project_id": "project-1", "message": "요청을 받았어요."}


def _wait_for(app: QApplication, predicate) -> None:
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.01)


def test_create_request_does_not_block_gui_while_auto_run_is_in_progress():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    window.show()
    _wait_for(app, lambda: window.current_state.get("state") == "idle")

    window.request_input.setText("Add a dashboard")
    started = time.monotonic()
    window._create_request()
    elapsed = time.monotonic() - started

    assert elapsed < 0.1
    assert not window.request_button.isEnabled()

    _wait_for(app, lambda: window.current_state.get("state") == "awaiting_approval")
    window.close()

    assert window.current_state.get("state") == "awaiting_approval"
    assert window.request_button.isEnabled()


def test_pet_mode_only_shows_character_and_bubble_until_command_surface_opens():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())

    assert window.character.objectName() == "assistantCharacter"
    assert window.assistant_input.objectName() == "assistantComposer"
    assert window.detail.objectName() == "assistantBubble"
    _wait_for(app, lambda: window.current_state.get("state") == "idle")
    assert window.detail.text() == "무엇을 도와드릴까요?"
    assert window.headline.isHidden()
    assert window.status_card.isHidden()
    assert window.command_surface.isHidden()
    assert window.legacy_panel.isHidden()
    window.show_command_surface()
    assert not window.command_surface.isHidden()
    window.close()


def test_enter_submits_the_assistant_command():
    app = QApplication.instance() or QApplication([])
    client = RouteClient()
    window = PetWindow(client)
    window.show_command_surface()
    _wait_for(app, lambda: not window._busy)
    window.assistant_input.setText("Todo 앱 만들어줘")
    window.assistant_input.returnPressed.emit()

    _wait_for(app, lambda: client.routed_text == "Todo 앱 만들어줘")

    assert client.routed_text == "Todo 앱 만들어줘"
    window.close()
