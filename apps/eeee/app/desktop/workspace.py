"""Desktop control center for EEEE, separate from the always-visible pet."""

from __future__ import annotations

from typing import Any


class WorkspaceWindow:
    """A real local workspace window backed by the EEEE control-plane API."""

    def __new__(cls, client: Any, *, language: str = "ko"):
        from PySide6.QtCore import QTimer, QUrl, Qt
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import (
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
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
                # Open on the project overview.  Each row is wired to a real
                # section renderer below; selection must never be cosmetic.
                self.nav.setCurrentRow(2)
                self.nav.currentRowChanged.connect(self._select_section)
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
                self.map_tree.itemSelectionChanged.connect(self._select_plugin)
                content.addWidget(self.map_tree, 1)
                self.plugin_actions = QWidget()
                self.plugin_actions_layout = QVBoxLayout(self.plugin_actions)
                self.plugin_actions_layout.setContentsMargins(0, 0, 0, 0)
                self.plugin_hint = QLabel()
                self.plugin_hint.setWordWrap(True)
                self.plugin_hint.setStyleSheet("color: #aeb5ce;")
                self.plugin_actions_layout.addWidget(self.plugin_hint)
                plugin_buttons = QHBoxLayout()
                self.plugin_install_button = QPushButton("설치" if language == "ko" else "Install")
                self.plugin_connect_button = QPushButton("연결" if language == "ko" else "Connect")
                self.plugin_disconnect_button = QPushButton("연결 해제" if language == "ko" else "Disconnect")
                self.plugin_install_button.clicked.connect(self._install_selected_plugin)
                self.plugin_connect_button.clicked.connect(self._connect_selected_plugin)
                self.plugin_disconnect_button.clicked.connect(self._disconnect_selected_plugin)
                plugin_buttons.addWidget(self.plugin_install_button)
                plugin_buttons.addWidget(self.plugin_connect_button)
                plugin_buttons.addWidget(self.plugin_disconnect_button)
                self.plugin_actions_layout.addLayout(plugin_buttons)
                content.addWidget(self.plugin_actions)
                self.events = QLabel()
                self.events.setWordWrap(True)
                self.events.setStyleSheet("color: #7b8198;")
                content.addWidget(self.events)
                root.addLayout(content, 1)
                self._snapshot: dict[str, object] = {}
                self._plugin_catalog: list[dict[str, object]] = []
                self._plugins_by_id: dict[str, dict[str, object]] = {}
                self._selected_plugin: dict[str, object] | None = None
                self._oauth_poll_timer = QTimer(self)
                self._oauth_poll_timer.setInterval(1000)
                self._oauth_poll_timer.timeout.connect(self._poll_oauth_connection)
                self._oauth_poll_plugin_id: str | None = None
                self._oauth_poll_attempts = 0
                self.plugin_actions.setVisible(False)
                self.refresh()

            def _select_section(self, row: int):
                """Render the section selected in the left navigation."""
                self._active_section = max(0, min(row, 5))
                if self._active_section == 3:
                    self._refresh_plugin_catalog()
                self._render_section()

            def _section_text(self, row: int) -> tuple[str, str]:
                labels = {
                    0: ("대화", "대화"),
                    1: ("진행 중", "진행 중인 작업"),
                    2: ("프로젝트", "프로젝트 실행 조직도"),
                    3: ("플러그인", "플러그인 연결 상태"),
                    4: ("기억", "EEEE가 기억하고 있는 내용"),
                    5: ("설정", "EEEE 설정"),
                }
                return labels.get(row, labels[2])

            def _render_section(self):
                """Update the visible content for the selected sidebar row."""
                if not hasattr(self, "map_tree"):
                    return
                row = getattr(self, "_active_section", self.nav.currentRow())
                self.plugin_actions.setVisible(row == 3)
                section, title = self._section_text(row)
                self.heading.setText(section if self.language == "ko" else {
                    0: "Chat", 1: "In progress", 2: "Projects", 3: "Plugins",
                    4: "Memory", 5: "Settings",
                }.get(row, "Projects"))
                self.map_title.setText(title if self.language == "ko" else {
                    0: "Conversation", 1: "Active work", 2: "Project execution map",
                    3: "Plugin connections", 4: "EEEE memory", 5: "EEEE settings",
                }.get(row, "Project execution map"))
                self.map_tree.clear()
                self._set_section_headers(row)
                if row == 2:
                    project_id = self._snapshot.get("projectId")
                    self._render_map(project_id if isinstance(project_id, str) else None)
                elif row == 1:
                    self._render_jobs()
                elif row == 3:
                    self._render_plugins()
                elif row == 4:
                    self._render_memory()
                elif row == 0:
                    item = QTreeWidgetItem([
                        "펫 Quick Chat에서 대화를 시작하세요" if self.language == "ko" else "Start a conversation from Pet Quick Chat",
                        "ready",
                        "",
                    ])
                    self.map_tree.addTopLevelItem(item)
                else:
                    item = QTreeWidgetItem([
                        "언어·프로필·연결 설정" if self.language == "ko" else "Language, profile, and connections",
                        "available",
                        "",
                    ])
                    self.map_tree.addTopLevelItem(item)

            def _set_section_headers(self, row: int):
                if row == 1:
                    labels = ("작업", "상태", "요청 ID")
                elif row == 3:
                    labels = ("플러그인", "상태", "연결 방식")
                elif row == 4:
                    labels = ("기억", "상태", "구분")
                else:
                    labels = (
                        "작업" if self.language == "ko" else "Work",
                        "상태" if self.language == "ko" else "Status",
                        "QA / ClaimLatch",
                    )
                self.map_tree.setHeaderLabels(list(labels))

            def _render_jobs(self):
                control_center = self._snapshot.get("controlCenter", {})
                jobs = control_center.get("jobs", []) if isinstance(control_center, dict) else []
                for job in jobs:
                    if not isinstance(job, dict):
                        continue
                    self.map_tree.addTopLevelItem(QTreeWidgetItem([
                        str(job.get("summary") or job.get("requestId") or "작업"),
                        str(job.get("status", "unknown")),
                        str(job.get("requestId", "")),
                    ]))
                if not jobs:
                    self.map_tree.addTopLevelItem(QTreeWidgetItem([
                        "진행 중인 작업이 없어" if self.language == "ko" else "No active work",
                        "idle", "",
                    ]))

            def _render_plugins(self):
                control_center = self._snapshot.get("controlCenter", {})
                snapshot_plugins = control_center.get("plugins", []) if isinstance(control_center, dict) else []
                plugins = self._plugin_catalog or [
                    item for item in snapshot_plugins if isinstance(item, dict)
                ]
                self._plugins_by_id = {}
                for plugin in plugins:
                    if not isinstance(plugin, dict):
                        continue
                    plugin_id = str(plugin.get("id") or plugin.get("pluginId") or "")
                    if not plugin_id:
                        continue
                    self._plugins_by_id[plugin_id] = plugin
                    item = QTreeWidgetItem([
                        str(plugin.get("name") or plugin.get("pluginId") or "플러그인"),
                        self._plugin_label(plugin).split(": ", 1)[-1],
                        str(plugin.get("authMode") or plugin.get("installSource") or "local"),
                    ])
                    item.setData(0, Qt.ItemDataRole.UserRole, plugin_id)
                    self.map_tree.addTopLevelItem(item)
                if not plugins:
                    self.map_tree.addTopLevelItem(QTreeWidgetItem([
                        "연결된 플러그인이 없어" if self.language == "ko" else "No plugins",
                        "idle", "",
                    ]))
                elif self._selected_plugin is not None:
                    selected_id = str(self._selected_plugin.get("id") or self._selected_plugin.get("pluginId") or "")
                    for index in range(self.map_tree.topLevelItemCount()):
                        item = self.map_tree.topLevelItem(index)
                        if item.data(0, Qt.ItemDataRole.UserRole) == selected_id:
                            self.map_tree.setCurrentItem(item)
                            break
                elif self.map_tree.topLevelItemCount() > 0:
                    self.map_tree.setCurrentItem(self.map_tree.topLevelItem(0))
                self._select_plugin()

            def _refresh_plugin_catalog(self):
                """Load the actionable catalog while keeping snapshot data as a fallback."""
                getter = getattr(self.client, "get_plugin_catalog", None)
                if not callable(getter):
                    return
                try:
                    catalog = getter()
                except Exception as exc:
                    self._set_plugin_hint(self._friendly_error(exc))
                    return
                if isinstance(catalog, list):
                    self._plugin_catalog = [item for item in catalog if isinstance(item, dict)]

            def _selected_plugin_id(self) -> str | None:
                item = self.map_tree.currentItem()
                if item is None:
                    return None
                value = item.data(0, Qt.ItemDataRole.UserRole)
                return str(value) if value else None

            def _select_plugin(self):
                plugin_id = self._selected_plugin_id()
                self._selected_plugin = self._plugins_by_id.get(plugin_id) if plugin_id else None
                plugin = self._selected_plugin
                if plugin is None:
                    self.plugin_install_button.setEnabled(False)
                    self.plugin_connect_button.setEnabled(False)
                    self.plugin_disconnect_button.setEnabled(False)
                    if getattr(self, "_active_section", 2) == 3:
                        self._set_plugin_hint("플러그인을 선택해줘." if self.language == "ko" else "Select a plugin.")
                    return
                status = str(plugin.get("status", "unknown"))
                self.plugin_install_button.setEnabled(status == "not_installed")
                self.plugin_connect_button.setEnabled(status in {
                    "available", "awaiting_authentication", "failed"
                })
                self.plugin_disconnect_button.setEnabled(status in {"connected", "paused"})
                self.plugin_connect_button.setText(
                    ("재연결" if self.language == "ko" else "Reconnect")
                    if status == "failed"
                    else ("연결" if self.language == "ko" else "Connect")
                )
                permissions = plugin.get("permissions", [])
                permission_text = ", ".join(str(item) for item in permissions) if isinstance(permissions, list) else ""
                auth_mode = str(plugin.get("authMode", ""))
                self._set_plugin_hint(
                    f"{plugin.get('description', '')}\n권한: {permission_text}\n인증 방식: {auth_mode}"
                    if self.language == "ko"
                    else f"{plugin.get('description', '')}\nPermissions: {permission_text}\nAuth: {auth_mode}"
                )

            def _set_plugin_hint(self, text: str):
                if hasattr(self, "plugin_hint"):
                    self.plugin_hint.setText(text)

            def _install_selected_plugin(self):
                plugin = self._selected_plugin
                if plugin is None:
                    return
                plugin_id = str(plugin.get("id") or plugin.get("pluginId") or "")
                try:
                    self.client.install_plugin(plugin_id)
                except Exception as exc:
                    self._set_plugin_hint(self._friendly_error(exc))
                    return
                self._set_plugin_hint("설치했어. 연결할 계정을 선택해줘." if self.language == "ko" else "Installed. Choose an account to connect.")
                self.refresh()

            def _disconnect_selected_plugin(self):
                plugin = self._selected_plugin
                if plugin is None:
                    return
                plugin_id = str(plugin.get("id") or plugin.get("pluginId") or "")
                try:
                    self.client.disconnect_plugin(plugin_id)
                except Exception as exc:
                    self._set_plugin_hint(self._friendly_error(exc))
                    return
                self._set_plugin_hint("연결을 해제했어." if self.language == "ko" else "Disconnected.")
                self.refresh()

            def _connect_selected_plugin(self):
                plugin = self._selected_plugin
                if plugin is None:
                    return
                self._show_plugin_connection_dialog(plugin)

            def _show_plugin_connection_dialog(self, plugin: dict[str, object]):
                dialog = QDialog(self)
                dialog.setWindowTitle(
                    f"{plugin.get('name', '플러그인')} 연결" if self.language == "ko"
                    else f"Connect {plugin.get('name', 'Plugin')}"
                )
                form = QFormLayout(dialog)
                description = QLabel(str(plugin.get("description", "")))
                description.setWordWrap(True)
                form.addRow(description)
                checks: list[QCheckBox] = []
                permissions = plugin.get("permissions", [])
                if not isinstance(permissions, list):
                    permissions = []
                for permission in permissions:
                    check = QCheckBox(str(permission))
                    check.setChecked(True)
                    checks.append(check)
                    form.addRow("권한" if self.language == "ko" else "Permission", check)
                account = QLineEdit()
                account.setPlaceholderText("예: 개인 계정" if self.language == "ko" else "e.g. Personal account")
                form.addRow("계정 이름" if self.language == "ko" else "Account label", account)
                auth_mode = str(plugin.get("authMode", ""))
                use_browser_oauth = QCheckBox("브라우저 OAuth로 연결" if self.language == "ko" else "Connect with browser OAuth")
                use_browser_oauth.setChecked(auth_mode == "oauth")
                use_browser_oauth.setVisible(auth_mode in {"oauth", "token-or-oauth"})
                form.addRow(use_browser_oauth)
                credential = QLineEdit()
                credential.setEchoMode(QLineEdit.EchoMode.Password)
                credential.setPlaceholderText("토큰은 저장하거나 표시하지 않아" if self.language == "ko" else "The token is never displayed")
                credential.setVisible(auth_mode in {"token", "token-or-oauth"})
                form.addRow("토큰" if self.language == "ko" else "Token", credential)
                parent_page = QLineEdit()
                parent_page.setPlaceholderText("Notion 부모 페이지 ID" if self.language == "ko" else "Notion parent page ID")
                parent_page.setVisible(str(plugin.get("id") or plugin.get("pluginId")) == "notion")
                form.addRow("부모 페이지" if self.language == "ko" else "Parent page", parent_page)
                buttons = QDialogButtonBox(
                    QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                )
                buttons.accepted.connect(dialog.accept)
                buttons.rejected.connect(dialog.reject)
                form.addRow(buttons)
                use_browser_oauth.toggled.connect(credential.setDisabled)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                approved = [check.text() for check in checks if check.isChecked()]
                if not approved:
                    self._set_plugin_hint("최소 한 개의 권한을 확인해야 해." if self.language == "ko" else "Approve at least one permission.")
                    return
                plugin_id = str(plugin.get("id") or plugin.get("pluginId") or "")
                if use_browser_oauth.isChecked():
                    self._start_oauth_connection(plugin, approved, account.text().strip() or None)
                    return
                token = credential.text()
                if not token:
                    self._set_plugin_hint("토큰을 입력해줘." if self.language == "ko" else "Enter a token.")
                    return
                credential_payload = {"token": token}
                if plugin_id == "notion":
                    parent_page_id = parent_page.text().strip()
                    if not parent_page_id:
                        self._set_plugin_hint("Notion 부모 페이지 ID를 입력해줘." if self.language == "ko" else "Enter a Notion parent page ID.")
                        return
                    credential_payload["parentPageId"] = parent_page_id
                try:
                    result = self.client.connect_plugin(
                        plugin_id, credential_payload, approved, account.text().strip() or None
                    )
                except Exception as exc:
                    self._set_plugin_hint(self._friendly_error(exc))
                    return
                status = str(result.get("status", "connected")) if isinstance(result, dict) else "connected"
                self._set_plugin_hint("연결됨" if status == "connected" and self.language == "ko" else status)
                self.refresh()

            def _start_oauth_connection(
                self,
                plugin: dict[str, object] | None,
                permissions: list[str],
                account_label: str | None = None,
            ):
                if plugin is None:
                    return
                plugin_id = str(plugin.get("id") or plugin.get("pluginId") or "")
                try:
                    result = self.client.start_plugin_oauth(plugin_id, permissions, account_label)
                    authorization_url = str(result.get("authorizationUrl", ""))
                    if not authorization_url:
                        raise RuntimeError("OAuth authorization URL is missing")
                    QDesktopServices.openUrl(QUrl(authorization_url))
                except Exception as exc:
                    self._set_plugin_hint(self._friendly_error(exc))
                    return
                self._oauth_poll_plugin_id = plugin_id
                self._oauth_poll_attempts = 0
                self._set_plugin_hint(
                    "브라우저에서 권한을 승인하면 연결 상태를 확인할게." if self.language == "ko"
                    else "Approve access in your browser; I will check the connection."
                )
                self._oauth_poll_timer.start()

            def _poll_oauth_connection(self):
                plugin_id = self._oauth_poll_plugin_id
                if not plugin_id:
                    self._oauth_poll_timer.stop()
                    return
                self._oauth_poll_attempts += 1
                try:
                    result = self.client.get_plugin_connection(plugin_id)
                except Exception as exc:
                    if self._oauth_poll_attempts >= 60:
                        self._oauth_poll_timer.stop()
                        self._oauth_poll_plugin_id = None
                        self._set_plugin_hint(self._friendly_error(exc))
                    return
                status = str(result.get("status", "")) if isinstance(result, dict) else ""
                if status == "connected":
                    self._oauth_poll_timer.stop()
                    self._oauth_poll_plugin_id = None
                    for candidate in self._plugin_catalog:
                        candidate_id = str(candidate.get("id") or candidate.get("pluginId") or "")
                        if candidate_id == plugin_id:
                            candidate["status"] = "connected"
                    if self._selected_plugin is not None:
                        self._selected_plugin["status"] = "connected"
                    self._set_plugin_hint("연결됨" if self.language == "ko" else "Connected")
                    self._render_section()
                    self._set_plugin_hint("연결됨" if self.language == "ko" else "Connected")
                elif status in {"failed", "disabled"}:
                    self._oauth_poll_timer.stop()
                    self._oauth_poll_plugin_id = None
                    self._set_plugin_hint("연결에 실패했어. 설정을 확인해줘." if self.language == "ko" else "Connection failed. Check the provider configuration.")
                elif self._oauth_poll_attempts >= 60:
                    self._oauth_poll_timer.stop()
                    self._oauth_poll_plugin_id = None
                    self._set_plugin_hint("연결 확인 시간이 만료됐어." if self.language == "ko" else "Connection check timed out.")

            def _friendly_error(self, exc: Exception) -> str:
                detail = str(exc).lower()
                if "oauth configuration" in detail:
                    return "이 플러그인은 OAuth 설정이 필요해. 관리자 설정을 확인해줘." if self.language == "ko" else "This plugin needs OAuth provider configuration."
                if "must be installed" in detail or "설치" in detail:
                    return "먼저 플러그인을 설치해줘." if self.language == "ko" else "Install the plugin first."
                if "permission" in detail or "권한" in detail:
                    return "선택한 권한을 확인해줘." if self.language == "ko" else "Check the approved permissions."
                return "플러그인 작업에 실패했어. 설정과 연결 상태를 확인해줘." if self.language == "ko" else "The plugin action failed. Check its configuration and connection."

            def _render_memory(self):
                control_center = self._snapshot.get("controlCenter", {})
                memory = control_center.get("memory", {}) if isinstance(control_center, dict) else {}
                active = memory.get("activeCount", 0) if isinstance(memory, dict) else 0
                candidates = memory.get("candidateCount", 0) if isinstance(memory, dict) else 0
                self.map_tree.addTopLevelItem(QTreeWidgetItem([
                    "활성 기억" if self.language == "ko" else "Active memories",
                    str(active), "accepted",
                ]))
                self.map_tree.addTopLevelItem(QTreeWidgetItem([
                    "검토 대기 기억" if self.language == "ko" else "Candidate memories",
                    str(candidates), "candidate",
                ]))

            def refresh(self):
                try:
                    snapshot = self.client.get_desktop_state()
                except Exception as exc:
                    self.status.setText(str(exc))
                    return
                self._snapshot = snapshot
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
                    plugin_labels = [
                        self._plugin_label(item)
                        for item in plugins if isinstance(item, dict)
                    ]
                    self.control_center.setText(
                        f"활성 작업 {active_jobs}개 · 활성 기억 {active_count}개 · "
                        f"검토 대기 기억 {candidate_count}개 · 플러그인 {len(plugins)}개"
                        + (f"\n{' · '.join(plugin_labels)}" if plugin_labels else "")
                    )
                else:
                    self.control_center.setText("EEEE 제어 센터 정보를 불러오는 중이야.")
                events = snapshot.get("events")
                if isinstance(events, list) and events:
                    labels = [str(item.get("kind", "event")) for item in events[-5:] if isinstance(item, dict)]
                    self.events.setText(("최근 이벤트: " if self.language == "ko" else "Recent events: ") + " · ".join(labels))
                else:
                    self.events.setText("최근 이벤트 없음" if self.language == "ko" else "No recent events")
                if getattr(self, "_active_section", 2) == 3:
                    self._refresh_plugin_catalog()
                self._render_section()

            def _plugin_label(self, plugin: dict[str, object]) -> str:
                name = plugin.get("name") or plugin.get("pluginId") or (
                    "플러그인" if self.language == "ko" else "Plugin"
                )
                status = str(plugin.get("status", "unknown"))
                labels = {
                    "ko": {
                        "not_installed": "설치 필요",
                        "awaiting_authentication": "연결 필요",
                        "connecting": "연결 중",
                        "connected": "연결됨",
                        "paused": "일시정지",
                        "failed": "오류",
                        "disabled": "설정 필요",
                        "available": "사용 가능",
                    },
                    "en": {
                        "not_installed": "Install required",
                        "awaiting_authentication": "Connect required",
                        "connecting": "Connecting",
                        "connected": "Connected",
                        "paused": "Paused",
                        "failed": "Error",
                        "disabled": "Configuration required",
                        "available": "Available",
                    },
                }
                status_label = labels.get(self.language, labels["en"]).get(status, "Unknown")
                return f"{name}: {status_label}"

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
