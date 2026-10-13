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
