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


def test_workspace_is_a_desktop_control_center_and_renders_project_map():
    app = QApplication.instance() or QApplication([])
    window = WorkspaceWindow(WorkspaceClient())

    assert window.windowTitle() == "EEEE Workspace"
    assert window.map_tree.topLevelItemCount() == 1
    assert window.map_tree.topLevelItem(0).text(0) == "Todo 프로젝트"
    assert window.map_tree.topLevelItem(0).child(0).text(0) == "독립 QA"
    assert window.map_tree.topLevelItem(0).child(0).text(1) == "▶ active"
    assert "QA 검증 중" in window.status.text()
    window.close()
