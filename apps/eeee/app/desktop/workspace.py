"""Desktop control center for EEEE, separate from the always-visible pet."""

from __future__ import annotations

from typing import Any


class WorkspaceWindow:
    """A real local workspace window backed by the EEEE control-plane API."""

    def __new__(cls, client: Any, *, language: str = "ko"):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QHBoxLayout,
            QLabel,
            QListWidget,
            QPushButton,
            QTreeWidget,
            QTreeWidgetItem,
            QVBoxLayout,
            QWidget,
        )

        class _Workspace(QWidget):
            def __init__(self):
                super().__init__()
                self.client = client
                self.language = language
                self.setWindowTitle("EEEE Workspace")
                self.setMinimumSize(980, 680)
                self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)

                root = QHBoxLayout(self)
                root.setContentsMargins(0, 0, 0, 0)
                sidebar = QVBoxLayout()
                sidebar.setContentsMargins(18, 22, 18, 22)
                sidebar.setSpacing(8)
                self.brand = QLabel("EEEE")
                self.brand.setStyleSheet("font-size: 26px; font-weight: 700;")
                sidebar.addWidget(self.brand)
                self.nav = QListWidget()
                self.nav.addItems([
                    "대화" if language == "ko" else "Chat",
                    "진행 중" if language == "ko" else "In progress",
                    "프로젝트" if language == "ko" else "Projects",
                    "플러그인" if language == "ko" else "Plugins",
                    "기억" if language == "ko" else "Memory",
                    "설정" if language == "ko" else "Settings",
                ])
                self.nav.setCurrentRow(1)
                sidebar.addWidget(self.nav, 1)
                self.refresh_button = QPushButton("새로고침" if language == "ko" else "Refresh")
                self.refresh_button.clicked.connect(self.refresh)
                sidebar.addWidget(self.refresh_button)
                root.addLayout(sidebar, 0)

                content = QVBoxLayout()
                content.setContentsMargins(26, 22, 26, 22)
                content.setSpacing(12)
                self.heading = QLabel("오늘 EEEE가 도와줄 일" if language == "ko" else "What EEEE is doing")
                self.heading.setStyleSheet("font-size: 24px; font-weight: 700;")
                content.addWidget(self.heading)
                self.status = QLabel()
                self.status.setWordWrap(True)
                self.status.setStyleSheet("font-size: 14px; padding: 14px; background: #202332; border-radius: 12px;")
                content.addWidget(self.status)
                self.control_center = QLabel()
                self.control_center.setWordWrap(True)
                self.control_center.setStyleSheet("color: #aeb5ce; padding: 10px; background: #181a24; border-radius: 10px;")
                content.addWidget(self.control_center)
                self.map_title = QLabel("프로젝트 실행 조직도" if language == "ko" else "Project execution map")
                self.map_title.setStyleSheet("font-size: 18px; font-weight: 600;")
                content.addWidget(self.map_title)
                self.map_tree = QTreeWidget()
                self.map_tree.setHeaderLabels([
                    "작업" if language == "ko" else "Work",
                    "상태" if language == "ko" else "Status",
                    "QA / ClaimLatch",
                ])
                self.map_tree.setColumnWidth(0, 360)
                content.addWidget(self.map_tree, 1)
                self.events = QLabel()
                self.events.setWordWrap(True)
                self.events.setStyleSheet("color: #7b8198;")
                content.addWidget(self.events)
                root.addLayout(content, 1)
                self.refresh()

            def refresh(self):
                try:
                    snapshot = self.client.get_desktop_state()
                except Exception as exc:
                    self.status.setText(str(exc))
                    return
                project_state = snapshot.get("projectState")
                state = snapshot.get("state")
                message = snapshot.get("message")
                if isinstance(project_state, dict):
                    state = project_state.get("state", state)
                    message = project_state.get("message", message)
                state = state if isinstance(state, str) else "idle"
                message = message if isinstance(message, str) else ""
                project_id = snapshot.get("projectId")
                self.status.setText(
                    f"상태: {state}\n{message}\n"
                    f"프로젝트: {project_id or '없음'}"
                    if self.language == "ko"
                    else f"Status: {state}\n{message}\nProject: {project_id or 'none'}"
                )
                control_center = snapshot.get("controlCenter")
                if isinstance(control_center, dict):
                    jobs = control_center.get("jobs", [])
                    memory = control_center.get("memory", {})
                    plugins = control_center.get("plugins", [])
                    active_jobs = sum(
                        1 for job in jobs
                        if isinstance(job, dict) and job.get("status") in {"queued", "running", "paused"}
                    )
                    active_count = memory.get("activeCount", 0) if isinstance(memory, dict) else 0
                    candidate_count = memory.get("candidateCount", 0) if isinstance(memory, dict) else 0
                    self.control_center.setText(
                        f"활성 작업 {active_jobs}개 · 활성 기억 {active_count}개 · "
                        f"검토 대기 기억 {candidate_count}개 · 플러그인 {len(plugins)}개"
                    )
                else:
                    self.control_center.setText("EEEE 제어 센터 정보를 불러오는 중이야.")
                self._render_map(project_id if isinstance(project_id, str) else None)
                events = snapshot.get("events")
                if isinstance(events, list) and events:
                    labels = [str(item.get("kind", "event")) for item in events[-5:] if isinstance(item, dict)]
                    self.events.setText(("최근 이벤트: " if self.language == "ko" else "Recent events: ") + " · ".join(labels))
                else:
                    self.events.setText("최근 이벤트 없음" if self.language == "ko" else "No recent events")

            def _render_map(self, project_id: str | None):
                self.map_tree.clear()
                if not project_id or not hasattr(self.client, "open_project"):
                    return
                try:
                    snapshot = self.client.open_project(project_id)
                except Exception as exc:
                    self.events.setText(str(exc))
                    return
                nodes = {str(node.get("id")): node for node in snapshot.get("nodes", []) if isinstance(node, dict)}
                children: dict[str, list[str]] = {node_id: [] for node_id in nodes}
                roots: list[str] = []
                for edge in snapshot.get("edges", []):
                    if not isinstance(edge, dict) or edge.get("kind") != "contains":
                        continue
                    source = str(edge.get("source"))
                    target = str(edge.get("target"))
                    if source in children and target in nodes:
                        children[source].append(target)
                targets = {target for values in children.values() for target in values}
                roots = [node_id for node_id in nodes if node_id not in targets]
                for node_id in roots:
                    self._append_node(None, node_id, nodes, children, snapshot.get("currentNodeIds", []))

            def _append_node(self, parent, node_id, nodes, children, current_ids):
                from PySide6.QtWidgets import QTreeWidgetItem

                node = nodes[node_id]
                status = str(node.get("status", "waiting"))
                if node_id in current_ids:
                    status = f"▶ {status}"
                item = QTreeWidgetItem([
                    str(node.get("title", node_id)),
                    status,
                    f"{node.get('qaStatus', 'unavailable')} / {node.get('claimLatchStatus', 'unavailable')}",
                ])
                if parent is None:
                    self.map_tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                for child_id in children.get(node_id, []):
                    self._append_node(item, child_id, nodes, children, current_ids)
                item.setExpanded(True)

        return _Workspace()
