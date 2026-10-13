import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.desktop.workspace import WorkspaceWindow


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


def test_workspace_is_a_desktop_control_center_and_renders_project_map():
    app = QApplication.instance() or QApplication([])
    window = WorkspaceWindow(WorkspaceClient())

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

    assert "QA 검증 중" in window.status.text()
    window.close()


def test_workspace_sidebar_selection_renders_the_selected_section():
    app = QApplication.instance() or QApplication([])
    window = WorkspaceWindow(WorkspaceClient())

    assert window.nav.currentRow() == 2
    assert window.heading.text() == "프로젝트"
    assert window.map_tree.topLevelItemCount() == 1

    window.nav.setCurrentRow(4)
    assert window.heading.text() == "기억"
    assert window.map_title.text() == "EEEE가 기억하고 있는 내용"
    assert window.map_tree.topLevelItem(0).text(0) == "활성 기억"

    window.nav.setCurrentRow(3)
    assert window.heading.text() == "플러그인"
    assert window.map_tree.topLevelItem(0).text(0) == "Notion"
    window.close()


def test_workspace_plugin_screen_exposes_install_and_disconnect_actions():
    app = QApplication.instance() or QApplication([])
    client = PluginWorkspaceClient()
    window = WorkspaceWindow(client)

    window.nav.setCurrentRow(3)
    assert window.map_tree.topLevelItemCount() == 1
    assert window.map_tree.topLevelItem(0).text(0) == "Notion"
    assert window.plugin_install_button.isEnabled()
    assert not window.plugin_connect_button.isEnabled()

    window._install_selected_plugin()
    assert client.calls == [("install", "notion")]
    assert window.plugin_connect_button.isEnabled()
    assert not window.plugin_install_button.isEnabled()

    window._disconnect_selected_plugin()
    assert client.calls[-1] == ("disconnect", "notion")
    assert window.plugin_connect_button.isEnabled()
    window.close()


def test_workspace_oauth_connection_opens_provider_and_polls_without_exposing_secrets(monkeypatch):
    app = QApplication.instance() or QApplication([])
    client = PluginWorkspaceClient()
    window = WorkspaceWindow(client)
    window.nav.setCurrentRow(3)
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

    assert opened == ["https://provider.test/authorize"]
    assert ("oauth", "notion", ["pages.read"], "workspace") in client.calls
    window._poll_oauth_connection()
    assert window._oauth_poll_timer.isActive() is False
    assert "연결됨" in window.plugin_hint.text()
    window.close()
