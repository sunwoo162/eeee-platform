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
        return {"state": "idle", "message": "Ready"}

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


def test_background_refresh_does_not_overwrite_a_foreground_request():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(SlowClient())
    calls = []
    window.refresh = lambda *, silent=False: calls.append(silent)
    window._busy = True

    window._background_refresh()

    assert calls == []
    window.close()
