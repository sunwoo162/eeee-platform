import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.desktop.workspace import WorkspaceWindow


def _settle() -> None:
    app = QApplication.instance()
    deadline = time.time() + 1.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)
    app.processEvents()


class WorkspaceClient:
    def get_desktop_state(self):
        return {
            "state": "verifying",
            "message": "QA 검증 중",
            "projectId": "project-todo",
            "events": [{"kind": "qa.started"}],
            "controlCenter": {
                "jobs": [{"status": "running", "requestId": "request-1"}],
                "memory": {"activeCount": 2, "candidateCount": 1},
                "plugins": [{"pluginId": "notion", "name": "Notion", "status": "not_installed"}],
            },
        }

    def open_project(self, project_id):
        assert project_id == "project-todo"
        return {
            "projectId": project_id,
            "nodes": [
                {"id": "root", "title": "Todo 프로젝트", "status": "active", "qaStatus": "unavailable", "claimLatchStatus": "unavailable"},
                {"id": "qa", "title": "독립 QA", "status": "active", "qaStatus": "WARN", "claimLatchStatus": "WARN"},
            ],
            "edges": [{"source": "root", "target": "qa", "kind": "contains"}],
            "currentNodeIds": ["qa"],
        }


class ProjectStateWorkspaceClient(WorkspaceClient):
    def get_desktop_state(self):
        snapshot = super().get_desktop_state()
        snapshot.pop("state")
        snapshot.pop("message")
        snapshot["projectState"] = {"state": "verifying", "message": "QA 검증 중"}
        return snapshot


class PluginWorkspaceClient(WorkspaceClient):
    def __init__(self):
        self.catalog = [{
            "id": "notion",
            "name": "Notion",
            "description": "Notion pages connector",
            "authMode": "token-or-oauth",
            "permissions": ["pages.read", "pages.write"],
            "installSource": "bundled-optional",
            "status": "not_installed",
            "nextAction": "install",
        }]
        self.calls = []

    def get_plugin_catalog(self):
        return self.catalog

    def install_plugin(self, plugin_id):
        self.calls.append(("install", plugin_id))
        self.catalog[0]["status"] = "awaiting_authentication"
        return {"pluginId": plugin_id, "status": "available"}

    def connect_plugin(self, plugin_id, credential, permissions, account_label=None):
        self.calls.append(("connect", plugin_id, credential, permissions, account_label))
        self.catalog[0]["status"] = "connected"
        return {"pluginId": plugin_id, "status": "connected"}

    def disconnect_plugin(self, plugin_id):
        self.calls.append(("disconnect", plugin_id))
        self.catalog[0]["status"] = "awaiting_authentication"
        return {"pluginId": plugin_id, "status": "awaiting_authentication"}

    def start_plugin_oauth(self, plugin_id, permissions, account_label=None):
        self.calls.append(("oauth", plugin_id, permissions, account_label))
        return {"pluginId": plugin_id, "authorizationUrl": "https://provider.test/authorize"}

    def get_plugin_connection(self, plugin_id):
        self.calls.append(("connection", plugin_id))
        return {"pluginId": plugin_id, "status": "connected"}

    def pause_plugin(self, plugin_id):
        self.calls.append(("pause", plugin_id))
        self.catalog[0]["status"] = "paused"
        return {"pluginId": plugin_id, "status": "paused"}

    def resume_plugin(self, plugin_id):
        self.calls.append(("resume", plugin_id))
        self.catalog[0]["status"] = "connected"
        return {"pluginId": plugin_id, "status": "connected"}

    def uninstall_plugin(self, plugin_id):
        self.calls.append(("uninstall", plugin_id))
        self.catalog[0]["status"] = "not_installed"
        return {"pluginId": plugin_id, "status": "not_installed"}


class ChatHistoryPluginWorkspaceClient(WorkspaceClient):
    base_url = "http://127.0.0.1:8123"

    def get_plugin_catalog(self):
        return [{
            "id": "eeee-chat-history",
            "name": "EEEE 채팅 기록",
            "description": "EEEE 대화를 기록하고 이어서 보내기",
            "authMode": "none",
            "permissions": ["conversation.read", "conversation.write"],
            "status": "connected",
        }]

    def get_plugin_launch_info(self, plugin_id):
        assert plugin_id == "eeee-chat-history"
        return {
            "pluginId": plugin_id,
            "entrypoint": str(Path(__file__).parents[2] / "plugins" / "eeee_chat_history" / "main.py"),
        }


def test_workspace_is_a_desktop_control_center_and_renders_project_map():
    app = QApplication.instance() or QApplication([])
    window = WorkspaceWindow(WorkspaceClient())
    _settle()

    assert window.windowTitle() == "EEEE Workspace"
    assert window.map_tree.topLevelItemCount() == 1
    assert window.map_tree.topLevelItem(0).text(0) == "Todo 프로젝트"
    assert window.map_tree.topLevelItem(0).child(0).text(0) == "독립 QA"
    assert window.map_tree.topLevelItem(0).child(0).text(1) == "▶ active"
    assert "QA 검증 중" in window.status.text()
    assert "활성 기억 2개" in window.control_center.text()
    assert "Notion: 설치 필요" in window.control_center.text()
    assert "not_installed" not in window.control_center.text()
    window.close()


def test_workspace_reads_project_state_when_api_uses_nested_snapshot():
    app = QApplication.instance() or QApplication([])
    window = WorkspaceWindow(ProjectStateWorkspaceClient())
    _settle()

    assert "QA 검증 중" in window.status.text()
    window.close()


def test_workspace_sidebar_selection_renders_the_selected_section():
    app = QApplication.instance() or QApplication([])
    window = WorkspaceWindow(WorkspaceClient())
    _settle()

    assert window.nav.currentRow() == 2
    assert window.heading.text() == "프로젝트"
    assert window.map_tree.topLevelItemCount() == 1

    window.nav.setCurrentRow(4)
    _settle()
    assert window.heading.text() == "기억"
    assert window.map_title.text() == "EEEE가 기억하고 있는 내용"
    assert window.map_tree.topLevelItem(0).text(0) == "활성 기억"

    window.nav.setCurrentRow(3)
    _settle()
    assert window.heading.text() == "플러그인"
    assert window.map_tree.topLevelItem(0).text(0) == "Notion"
    window.close()


def test_workspace_plugin_screen_exposes_install_and_disconnect_actions():
    app = QApplication.instance() or QApplication([])
    client = PluginWorkspaceClient()
    window = WorkspaceWindow(client)
    _settle()

    window.nav.setCurrentRow(3)
    _settle()
    assert window.map_tree.topLevelItemCount() == 1
    assert window.map_tree.topLevelItem(0).text(0) == "Notion"
    assert window.plugin_install_button.isEnabled()
    assert not window.plugin_connect_button.isEnabled()

    window._install_selected_plugin()
    _settle()
    assert client.calls == [("install", "notion")]
    assert window.plugin_connect_button.isEnabled()
    assert not window.plugin_install_button.isEnabled()

    window._disconnect_selected_plugin()
    _settle()
    assert client.calls[-1] == ("disconnect", "notion")
    assert window.plugin_connect_button.isEnabled()
    window.close()


def test_workspace_opens_eeee_chat_history_as_a_separate_plugin_process(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = WorkspaceWindow(ChatHistoryPluginWorkspaceClient())
    _settle()
    window.nav.setCurrentRow(3)
    _settle()

    assert window.plugin_open_button.isEnabled()
    launched = []
    monkeypatch.setattr(
        "app.desktop.workspace.subprocess.Popen",
        lambda command, **kwargs: launched.append((command, kwargs)),
    )
    window._open_selected_plugin()
    _settle()

    assert launched
    assert "--api-url" in launched[0][0]
    assert "eeee_chat_history" in launched[0][0][1]
    window.close()


def test_workspace_oauth_connection_opens_provider_and_polls_without_exposing_secrets(monkeypatch):
    app = QApplication.instance() or QApplication([])
    client = PluginWorkspaceClient()
    window = WorkspaceWindow(client)
    _settle()
    window.nav.setCurrentRow(3)
    _settle()
    window.map_tree.setCurrentItem(window.map_tree.topLevelItem(0))

    opened = []
    monkeypatch.setattr(
        "PySide6.QtGui.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    window._start_oauth_connection(
        window._selected_plugin,
        ["pages.read"],
        "workspace",
    )
    _settle()

    assert opened == ["https://provider.test/authorize"]
    assert ("oauth", "notion", ["pages.read"], "workspace") in client.calls
    window._poll_oauth_connection()
    _settle()
    assert window._oauth_poll_timer.isActive() is False
    assert "연결됨" in window.plugin_hint.text()
    window.close()


def test_workspace_exposes_complete_plugin_lifecycle_actions():
    app = QApplication.instance() or QApplication([])
    client = PluginWorkspaceClient()
    window = WorkspaceWindow(client)
    _settle()
    window.nav.setCurrentRow(3)
    _settle()

    assert hasattr(window, "plugin_resume_button")
    assert hasattr(window, "plugin_open_button")
    assert hasattr(window, "plugin_uninstall_button")

    client.catalog[0]["status"] = "paused"
    window._render_section()
    assert window.plugin_resume_button.isEnabled()
    assert window.plugin_uninstall_button.isEnabled()

    window._resume_selected_plugin()
    _settle()
    assert client.calls[-1] == ("resume", "notion")
    window._uninstall_selected_plugin()
    _settle()
    assert client.calls[-1] == ("uninstall", "notion")
    window.close()


def test_workspace_refresh_runs_api_call_off_the_gui_thread():
    app = QApplication.instance() or QApplication([])

    class ThreadRecordingClient(WorkspaceClient):
        def __init__(self):
            self.threads = []

        def get_desktop_state(self):
            self.threads.append(threading.get_ident())
            return super().get_desktop_state()

    client = ThreadRecordingClient()
    window = WorkspaceWindow(client)
    client.threads.clear()
    gui_thread = threading.get_ident()

    window.refresh()
    QTest.qWait(150)

    assert client.threads
    assert client.threads[-1] != gui_thread
    window.close()
