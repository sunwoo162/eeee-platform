"""PySide6 desktop companion window."""

from app.desktop.client import PetApiClient
from app.desktop.presentation import PetPresentation
from app.desktop.session import DesktopSession
from app.desktop.worker import QtTaskRunner


_DESKTOP_TEXT = {
    "ko": {
        "window_title": "EEEE • Gleave",
        "language": "언어",
        "ready": "준비됨",
        "start_hint": "",
        "project_none": "프로젝트: 선택되지 않음",
        "runtime_none": "실행 프로필: 선택되지 않음",
        "runtime_prefix": "실행 프로필",
        "quality_prefix": "품질",
        "deployment_prefix": "배포 준비",
        "configuration_prefix": "추가 설정 필요",
        "claim_checking": "ClaimLatch: 확인 중",
        "mobile_available": "모바일 브리지: 데스크톱에서 연결 가능",
        "assistant_placeholder": "EEEE에게 다음 할 일을 물어보세요…",
        "ask": "EEEE에게 묻기",
        "pairing": "휴대폰 연결 코드",
        "pairing_none": "연결 코드 없음",
        "events_none": "최근 EEEE 이벤트 없음",
        "open_workspace": "Gleave 워크스페이스 열기",
        "hide": "트레이로 숨기기",
        "connecting": "로컬 EEEE 코디네이터에 연결 중…",
        "assistant_busy": "EEEE가 가장 적합한 기능을 선택하는 중…",
        "chatgpt_login": "ChatGPT 연결 창 열기",
        "chatgpt_opened": "Chrome에서 ChatGPT 로그인 후 EEEE에게 말해줘.",
        "pairing_busy": "짧은 휴대폰 연결 코드를 발급하는 중…",
        "project_prefix": "프로젝트",
        "claim_prefix": "ClaimLatch",
        "mobile_prefix": "모바일 브리지",
        "mobile_paired": "연결된 기기 {count}대",
        "recent_prefix": "최근",
        "phone_code": "휴대폰 코드: {code}",
        "expires": " (만료 {expires})",
        "headline": {
            "idle": "준비됨",
            "researching": "조사 중",
            "awaiting_approval": "승인 필요",
            "working": "작업 중",
            "verifying": "검증 중",
            "completed": "완료됨",
            "blocked": "중단됨",
            "failed": "실패",
        },
    },
    "en": {
        "window_title": "EEEE • Gleave",
        "language": "Language",
        "ready": "Ready",
        "start_hint": "",
        "project_none": "Project: none selected",
        "runtime_none": "Runtime profile: none selected",
        "runtime_prefix": "Runtime profile",
        "quality_prefix": "Quality",
        "deployment_prefix": "Deployment readiness",
        "configuration_prefix": "Configuration needed",
        "claim_checking": "ClaimLatch: checking",
        "mobile_available": "Mobile bridge: available from Desktop",
        "assistant_placeholder": "Ask EEEE what to do next…",
        "ask": "Ask EEEE",
        "pairing": "Pair phone",
        "pairing_none": "No pairing code issued",
        "events_none": "No recent EEEE events",
        "open_workspace": "Open Gleave workspace",
        "hide": "Hide to tray",
        "connecting": "Connecting to the local EEEE coordinator…",
        "assistant_busy": "EEEE is selecting the best capability…",
        "chatgpt_login": "Open ChatGPT connection",
        "chatgpt_opened": "Sign in to ChatGPT in Chrome, then talk to EEEE.",
        "pairing_busy": "Issuing a short-lived phone pairing code…",
        "project_prefix": "Project",
        "claim_prefix": "ClaimLatch",
        "mobile_prefix": "Mobile bridge",
        "mobile_paired": "{count} paired device(s)",
        "recent_prefix": "Recent",
        "phone_code": "Phone code: {code}",
        "expires": " (expires {expires})",
        "headline": {
            "idle": "Ready",
            "researching": "Researching",
            "awaiting_approval": "Approval needed",
            "working": "Working",
            "verifying": "Verifying",
            "completed": "Completed",
            "blocked": "Blocked",
            "failed": "Failed",
        },
    },
}


class PetWindow:
    """Build the GUI lazily so importing the desktop package stays display-free."""

    def __new__(
        cls,
        client: PetApiClient,
        *,
        initial_error: str | None = None,
        on_open_chatgpt=None,
    ):
        try:
            from PySide6.QtCore import QEvent, QSettings, QTimer, Qt
            from PySide6.QtGui import QAction, QFont
            from PySide6.QtWidgets import (
                QComboBox,
                QFrame,
                QHBoxLayout,
                QLabel,
                QLineEdit,
                QMenu,
                QPushButton,
                QApplication,
                QStyle,
                QSystemTrayIcon,
                QVBoxLayout,
                QWidget,
            )
        except ImportError as exc:
            raise RuntimeError(
                'PySide6 is required for the desktop shell. Install with `pip install -e ".[desktop]"`.'
            ) from exc

        class _Window(QWidget):
            def __init__(self):
                super().__init__()
                self.client = client
                self._on_open_chatgpt = on_open_chatgpt
                self.session = DesktopSession(client)
                self.current_state: dict[str, object] = {}
                self.desktop_snapshot: dict[str, object] = {}
                self._drag_offset = None
                self._busy = False
                self._refreshing = False
                self._closing = False
                self._quit_requested = False
                self._tray = None
                self._task_runner = QtTaskRunner(parent=self)
                self._settings = QSettings("Gleave", "GleaveDesktop")
                saved_language = self._settings.value("language", "ko")
                self.language = saved_language if saved_language in _DESKTOP_TEXT else "ko"
                self.setObjectName("desktopCompanion")
                self.setWindowTitle(self._text("window_title"))
                self.setWindowFlags(
                    Qt.WindowType.FramelessWindowHint
                    | Qt.WindowType.WindowStaysOnTopHint
                    | Qt.WindowType.Tool
                )
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                self.setAutoFillBackground(True)
                self.setMinimumWidth(360)
                self.setMaximumWidth(520)

                root = QVBoxLayout(self)
                root.setContentsMargins(22, 18, 22, 20)
                root.setSpacing(12)

                language_row_widget = QWidget()
                language_row = QHBoxLayout(language_row_widget)
                language_row.setContentsMargins(0, 0, 0, 0)
                self.language_label = QLabel()
                self.language_select = QComboBox()
                self.language_select.addItem("한국어", "ko")
                self.language_select.addItem("English", "en")
                self.language_select.setCurrentIndex(0 if self.language == "ko" else 1)
                self.language_select.currentIndexChanged.connect(self._change_language)
                language_row.addStretch(1)
                language_row.addWidget(self.language_label)
                language_row.addWidget(self.language_select)
                root.addWidget(language_row_widget)

                self.character = QLabel("🐾")
                self.character.setObjectName("assistantCharacter")
                self.character.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.character.setFont(QFont("Segoe UI Emoji", 34))
                self.character.installEventFilter(self)
                root.addWidget(self.character)

                self.headline = QLabel()
                self.headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.headline.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
                root.addWidget(self.headline)

                self.detail = QLabel()
                self.detail.setObjectName("assistantBubble")
                self.detail.setWordWrap(True)
                self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
                root.addWidget(self.detail)

                self.status_card = QFrame()
                self.status_card.setObjectName("projectStatusCard")
                status_layout = QVBoxLayout(self.status_card)
                status_layout.setContentsMargins(14, 10, 14, 10)
                status_layout.setSpacing(5)
                self.project_status = QLabel()
                self.project_status.setWordWrap(True)
                self.project_status.setObjectName("projectStatus")
                status_layout.addWidget(self.project_status)
                self.runtime_status = QLabel()
                self.runtime_status.setWordWrap(True)
                self.runtime_status.setObjectName("runtimeStatus")
                status_layout.addWidget(self.runtime_status)
                self.trust_status = QLabel()
                self.trust_status.setWordWrap(True)
                self.trust_status.setObjectName("trustStatus")
                status_layout.addWidget(self.trust_status)
                self.mobile_status = QLabel()
                self.mobile_status.setWordWrap(True)
                self.mobile_status.setObjectName("mobileStatus")
                status_layout.addWidget(self.mobile_status)
                root.addWidget(self.status_card)

                self.command_surface = QFrame()
                self.command_surface.setObjectName("commandSurface")
                command_layout = QVBoxLayout(self.command_surface)
                command_layout.setContentsMargins(0, 0, 0, 0)
                assistant_row = QHBoxLayout()
                self.assistant_input = QLineEdit()
                self.assistant_input.setObjectName("assistantComposer")
                self.assistant_input.installEventFilter(self)
                self.assistant_button = QPushButton()
                self.assistant_button.setObjectName("primaryAction")
                self.assistant_button.clicked.connect(self._route_assistant)
                self.assistant_input.returnPressed.connect(self._route_assistant)
                assistant_row.addWidget(self.assistant_input)
                assistant_row.addWidget(self.assistant_button)
                command_layout.addLayout(assistant_row)
                self.chatgpt_button = QPushButton()
                self.chatgpt_button.setObjectName("secondaryAction")
                self.chatgpt_button.clicked.connect(self._open_chatgpt_login)
                self.chatgpt_button.setVisible(self._on_open_chatgpt is not None)
                command_layout.addWidget(self.chatgpt_button)
                root.addWidget(self.command_surface)
                self.command_surface.installEventFilter(self)

                actions_row = QHBoxLayout()
                self.pairing_button = QPushButton()
                self.pairing_button.setObjectName("secondaryAction")
                self.pairing_button.clicked.connect(self._issue_pairing_code)
                self.pairing_status = QLabel()
                self.pairing_status.setWordWrap(True)
                actions_row.addWidget(self.pairing_button)
                actions_row.addWidget(self.pairing_status, 1)
                root.addLayout(actions_row)

                self.events_view = QLabel()
                self.events_view.setWordWrap(True)
                root.addWidget(self.events_view)

                self.workspace_button = QPushButton()
                self.workspace_button.setObjectName("secondaryAction")
                self.workspace_button.clicked.connect(self._open_workspace)
                root.addWidget(self.workspace_button)

                self.hide_button = QPushButton()
                self.hide_button.setObjectName("secondaryAction")
                self.hide_button.clicked.connect(self.hide_to_tray)
                root.addWidget(self.hide_button)

                self.legacy_panel = QWidget()
                legacy_layout = QVBoxLayout(self.legacy_panel)
                legacy_layout.setContentsMargins(0, 0, 0, 0)
                legacy_layout.setSpacing(8)

                request_row = QHBoxLayout()
                self.request_input = QLineEdit()
                self.request_input.setPlaceholderText("What should we build?")
                self.request_button = QPushButton("Start")
                self.request_button.clicked.connect(self._create_request)
                request_row.addWidget(self.request_input)
                request_row.addWidget(self.request_button)
                legacy_layout.addLayout(request_row)

                self.candidate_select = QComboBox()
                self.approve_button = QPushButton("Approve selection")
                self.approve_button.clicked.connect(self._approve)
                legacy_layout.addWidget(self.candidate_select)
                legacy_layout.addWidget(self.approve_button)

                self.advance_button = QPushButton("Advance demo step")
                self.advance_button.clicked.connect(self._advance)
                legacy_layout.addWidget(self.advance_button)

                self.retry_button = QPushButton("Retry")
                self.retry_button.clicked.connect(self._retry)
                legacy_layout.addWidget(self.retry_button)
                self.legacy_panel.setVisible(False)
                root.addWidget(self.legacy_panel)

                language_row_widget.hide()
                self.headline.hide()
                self.status_card.hide()
                self.command_surface.hide()
                self.pairing_button.hide()
                self.pairing_status.hide()
                self.events_view.hide()
                self.workspace_button.hide()
                self.hide_button.hide()

                self.setStyleSheet(
                    "#desktopCompanion { background: #171923; border: 1px solid #35394b; "
                    "border-radius: 24px; color: #f4f3fb; }"
                    "#desktopCompanion QLabel { background: transparent; border: none; "
                    "color: #f4f3fb; }"
                    "#assistantCharacter { padding: 4px; }"
                    "#assistantBubble { background: #272a39; border: 1px solid #464b65; "
                    "border-radius: 14px; padding: 10px 14px; color: #dedcff; }"
                    "#projectStatusCard { background: #202332; border: 1px solid #373c53; "
                    "border-radius: 14px; }"
                    "#projectStatus { color: #ffffff; font-weight: 600; }"
                    "#runtimeStatus, #trustStatus, #mobileStatus { color: #b9bdd0; font-size: 11px; }"
                    "#desktopCompanion QLineEdit, #desktopCompanion QComboBox { "
                    "background: #252838; padding: 10px 12px; border: 1px solid #4b516c; "
                    "border-radius: 11px; color: #f4f3fb; selection-background-color: #5d55bc; }"
                    "#desktopCompanion QPushButton { background: #8f7cff; padding: 10px 12px; "
                    "border: none; border-radius: 11px; color: #ffffff; font-weight: 600; }"
                    "#desktopCompanion QPushButton:hover { background: #a69aff; }"
                    "#desktopCompanion QPushButton#secondaryAction { background: #2a2d3d; "
                    "border: 1px solid #464b65; color: #d9d8e8; font-weight: 500; }"
                    "#desktopCompanion QPushButton#secondaryAction:hover { background: #35394d; }"
                    "#desktopCompanion QPushButton:disabled { background: #3b414d; color: #8e96a5; }"
                    "#desktopCompanion QComboBox QAbstractItemView { background: #2b303b; "
                    "color: #f3f5f8; selection-background-color: #5147a5; }"
                )
                self._apply_language()
                self._timer = QTimer(self)
                self._timer.timeout.connect(self._background_refresh)
                self._setup_tray(QApplication, QStyle, QSystemTrayIcon, QAction, QMenu)
                if initial_error:
                    self._render({"state": "blocked", "message": initial_error})
                else:
                    self._timer.start(5000)
                    self.refresh()

            def eventFilter(self, watched, event):
                assistant_input = getattr(self, "assistant_input", None)
                command_surface = getattr(self, "command_surface", None)
                if (
                    watched in (assistant_input, command_surface)
                    and event.type() == QEvent.Type.KeyPress
                    and event.key() == Qt.Key.Key_Escape
                ):
                    self.hide_command_surface()
                    return True
                if (
                    watched is self.character
                    and event.type() == QEvent.Type.MouseButtonDblClick
                ):
                    self.show_command_surface()
                    return True
                return super().eventFilter(watched, event)

            def show_command_surface(self):
                self.command_surface.show()
                self.assistant_input.setFocus()

            def hide_command_surface(self):
                self.command_surface.hide()
                self.clearFocus()

            def mousePressEvent(self, event):
                if (
                    event.button() == Qt.MouseButton.LeftButton
                    and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                ):
                    self._open_workspace()
                    event.accept()
                    return
                if event.button() == Qt.MouseButton.LeftButton:
                    self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                super().mousePressEvent(event)

            def mouseMoveEvent(self, event):
                if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
                    self.move(event.globalPosition().toPoint() - self._drag_offset)
                super().mouseMoveEvent(event)

            def mouseReleaseEvent(self, event):
                self._drag_offset = None
                super().mouseReleaseEvent(event)

            def closeEvent(self, event):
                if self._tray is not None and not self._quit_requested:
                    self.hide_to_tray()
                    event.ignore()
                    return
                self._closing = True
                self._timer.stop()
                self._task_runner.shutdown()
                if self._tray is not None:
                    self._tray.hide()
                super().closeEvent(event)

            def _setup_tray(self, QApplication, QStyle, QSystemTrayIcon, QAction, QMenu):
                if not QSystemTrayIcon.isSystemTrayAvailable():
                    return
                self._double_click_reason = QSystemTrayIcon.ActivationReason.DoubleClick
                icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
                self._tray = QSystemTrayIcon(icon, self)
                self._tray.setToolTip("EEEE local assistant")
                menu = QMenu(self)
                show_action = QAction("Show EEEE", self)
                show_action.triggered.connect(self.restore_from_tray)
                hide_action = QAction("Hide", self)
                hide_action.triggered.connect(self.hide_to_tray)
                quit_action = QAction("Quit", self)
                quit_action.triggered.connect(self.request_quit)
                menu.addAction(show_action)
                menu.addAction(hide_action)
                menu.addSeparator()
                menu.addAction(quit_action)
                self._tray.setContextMenu(menu)
                self._tray.activated.connect(self._on_tray_activated)
                self._tray.show()

            def _on_tray_activated(self, reason):
                if self._tray is not None and reason == self._double_click_reason:
                    self.restore_from_tray()

            def hide_to_tray(self):
                self.hide()

            def restore_from_tray(self):
                self.showNormal()
                self.raise_()
                self.activateWindow()

            def request_quit(self):
                self._quit_requested = True
                self.close()

            def _text(self, key: str) -> str:
                value = _DESKTOP_TEXT[self.language].get(key, key)
                return value if isinstance(value, str) else key

            def _change_language(self, index: int):
                language = self.language_select.itemData(index)
                if language not in _DESKTOP_TEXT:
                    return
                self.language = language
                self._settings.setValue("language", language)
                self._apply_language()
                self._render_desktop_status(self.desktop_snapshot)

            def _apply_language(self):
                self.setWindowTitle(self._text("window_title"))
                self.language_label.setText(self._text("language"))
                self.assistant_input.setPlaceholderText(self._text("assistant_placeholder"))
                self.assistant_button.setText(self._text("ask"))
                self.chatgpt_button.setText(self._text("chatgpt_login"))
                self.pairing_button.setText(self._text("pairing"))
                self.pairing_status.setText(self._text("pairing_none"))
                self.workspace_button.setText(self._text("open_workspace"))
                self.hide_button.setText(self._text("hide"))
                if not self.current_state:
                    self.headline.setText(self._text("ready"))
                    self.detail.setText(self._text("start_hint"))
                    self.project_status.setText(self._text("project_none"))
                    self.runtime_status.setText(self._text("runtime_none"))
                    self.trust_status.setText(self._text("claim_checking"))
                    self.mobile_status.setText(self._text("mobile_available"))
                    self.events_view.setText(self._text("events_none"))
                self._update_controls()

            def refresh(self, *, silent: bool = False):
                def operation():
                    legacy_state = self.client.get_state()
                    if not hasattr(self.client, "get_desktop_state"):
                        return legacy_state
                    snapshot = self.session.refresh()
                    project_state = snapshot.get("projectState")
                    if isinstance(project_state, dict):
                        return {**snapshot, **project_state}
                    return {**snapshot, **legacy_state}

                self._submit(operation, self._text("connecting"), silent=silent)

            def _background_refresh(self):
                self.refresh(silent=True)

            def _update_controls(self):
                view = PetPresentation.from_view_model(self.current_state)
                self.request_input.setEnabled(not self._busy)
                self.request_button.setEnabled(not self._busy)
                self.assistant_input.setEnabled(not self._busy)
                self.assistant_button.setEnabled(not self._busy)
                self.candidate_select.setEnabled(not self._busy)
                self.approve_button.setEnabled(
                    not self._busy and view.show_approval and self.candidate_select.count() > 0
                )
                self.advance_button.setEnabled(
                    not self._busy and view.state in {"researching", "working", "verifying"}
                )
                self.retry_button.setEnabled(
                    not self._busy and view.state in {"blocked", "failed"}
                )
                self.workspace_button.setEnabled(
                    not self._busy
                )

            def _submit(self, operation, busy_message: str, on_success=None, *, silent=False):
                if self._closing or (self._busy and not silent) or (silent and self._refreshing):
                    return
                if silent:
                    self._refreshing = True
                else:
                    self._busy = True
                    self.detail.setText(busy_message)
                    self._update_controls()

                def success(payload):
                    if self._closing:
                        return
                    if silent:
                        self._refreshing = False
                    else:
                        self._busy = False
                    if on_success is None:
                        self._render(payload)
                    else:
                        on_success(payload)

                def failure(error):
                    if self._closing:
                        return
                    if silent:
                        self._refreshing = False
                        return
                    self._busy = False
                    failed_payload = dict(self.current_state)
                    failed_payload.update({"state": "blocked", "message": str(error)})
                    self._render(failed_payload)

                try:
                    self._task_runner.submit(operation, success, failure)
                except RuntimeError as exc:
                    failure(exc)

            def _render(self, payload: dict[str, object]):
                self.desktop_snapshot = payload if "claimLatch" in payload else self.desktop_snapshot
                project_state = payload.get("projectState")
                view_payload = (
                    {**payload, **project_state}
                    if isinstance(project_state, dict)
                    else payload
                )
                if not isinstance(view_payload.get("state"), str):
                    assistant_route = payload.get("assistantRoute")
                    if isinstance(assistant_route, dict):
                        view_payload = {
                            **view_payload,
                            "state": "idle",
                            "message": assistant_route.get(
                                "message", "EEEE completed the request."
                            ),
                        }
                self.current_state = view_payload
                view = PetPresentation.from_view_model(view_payload)
                self.character.setText({
                    "sleepy": "😴",
                    "curious": "🔎",
                    "thinking": "🤔",
                    "focused": "🛠️",
                    "checking": "🧪",
                    "happy": "🎉",
                    "alert": "⚠️",
                    "worried": "😟",
                    "confused": "❔",
                }[view.expression])
                headlines = _DESKTOP_TEXT[self.language]["headline"]
                self.headline.setText(headlines.get(view.state, view.headline))
                detail = view.detail
                if view.state == "idle" and detail == "Ready for a development request":
                    detail = self._text("start_hint")
                self.detail.setText(detail)
                self._render_desktop_status(payload)
                candidates = payload.get("candidates", [])
                self.candidate_select.clear()
                for candidate in candidates if isinstance(candidates, list) else []:
                    if isinstance(candidate, dict):
                        repository = candidate.get("repository", {})
                        if isinstance(repository, dict) and isinstance(repository.get("full_name"), str):
                            self.candidate_select.addItem(repository["full_name"])
                self._update_controls()

            def _render_desktop_status(self, payload: dict[str, object]) -> None:
                project_id = payload.get("projectId")
                self.project_status.setText(
                    f"{self._text('project_prefix')}: {project_id}"
                    if isinstance(project_id, str)
                    else self._text("project_none")
                )
                profile = payload.get("projectProfile")
                if isinstance(profile, dict):
                    runtime_profile = profile.get("runtimeProfile")
                    quality_status = payload.get("qualityStatus")
                    readiness = profile.get("provisioningStatus")
                    connectors = profile.get("connectors", [])
                    missing = [
                        str(connector.get("connectorId"))
                        for connector in connectors
                        if isinstance(connector, dict)
                        and connector.get("state") == "awaiting_configuration"
                        and isinstance(connector.get("connectorId"), str)
                    ] if isinstance(connectors, list) else []
                    status_parts = []
                    if isinstance(runtime_profile, str):
                        status_parts.append(f"{self._text('runtime_prefix')}: {runtime_profile}")
                    if isinstance(quality_status, str):
                        status_parts.append(f"{self._text('quality_prefix')}: {quality_status}")
                    if isinstance(readiness, str):
                        status_parts.append(f"{self._text('deployment_prefix')}: {readiness}")
                    if missing:
                        status_parts.append(
                            f"{self._text('configuration_prefix')}: {', '.join(missing)}"
                        )
                    self.runtime_status.setText(" • ".join(status_parts) or self._text("runtime_none"))
                else:
                    self.runtime_status.setText(self._text("runtime_none"))
                claim_latch = payload.get("claimLatch")
                if isinstance(claim_latch, dict):
                    status = claim_latch.get("status", "unknown")
                    profile = claim_latch.get("profileVersion", "unknown")
                    self.trust_status.setText(
                        f"{self._text('claim_prefix')}: {status} • {profile}"
                    )
                mobile = payload.get("mobileBridge")
                if isinstance(mobile, dict):
                    paired = mobile.get("pairedDevices", 0)
                    self.mobile_status.setText(
                        f"{self._text('mobile_prefix')}: "
                        f"{self._text('mobile_paired').format(count=paired)}"
                    )
                events = payload.get("events")
                if isinstance(events, list) and events:
                    labels = [
                        str(event.get("kind", "event"))
                        for event in events[-4:]
                        if isinstance(event, dict)
                    ]
                    self.events_view.setText(
                        f"{self._text('recent_prefix')}: " + " • ".join(labels)
                    )
                elif "claimLatch" in payload:
                    self.events_view.setText(self._text("events_none"))

            def _route_assistant(self):
                text = self.assistant_input.text().strip()
                if not text:
                    return
                self.hide_command_surface()

                def on_success(payload):
                    self.assistant_input.clear()
                    self._render(payload)

                self._submit(
                    lambda: self.session.route(text),
                    self._text("assistant_busy"),
                    on_success=on_success,
                )

            def _open_chatgpt_login(self):
                if self._on_open_chatgpt is None:
                    return

                def on_success(opened):
                    self.detail.setText(
                        self._text("chatgpt_opened") if opened else "ChatGPT 연결 창을 열 수 없어."
                    )

                self._submit(
                    self._on_open_chatgpt,
                    self._text("connecting"),
                    on_success=on_success,
                )

            def _issue_pairing_code(self):
                def on_success(payload):
                    code = payload.get("code")
                    expires = payload.get("expiresAt")
                    if isinstance(code, str):
                        suffix = (
                            self._text("expires").format(expires=expires)
                            if isinstance(expires, str)
                            else ""
                        )
                        self.pairing_status.setText(
                            f"{self._text('phone_code').format(code=code)}{suffix}"
                        )

                self._submit(
                    self.session.issue_pairing_code,
                    self._text("pairing_busy"),
                    on_success=on_success,
                )

            def _create_request(self):
                text = self.request_input.text().strip()
                if not text:
                    return

                def operation():
                    payload = self.client.create_request(text)
                    task_id = payload.get("task_id")
                    if payload.get("state") == "researching" and isinstance(task_id, str):
                        return self.client.run(task_id)
                    return payload

                def on_success(payload):
                    self.request_input.clear()
                    self._render(payload)

                self._submit(operation, "Starting research...", on_success=on_success)

            def _approve(self):
                request_id = self.current_state.get("request_id")
                task_id = self.current_state.get("task_id")
                selected = self.candidate_select.currentText()
                if isinstance(request_id, str) and selected:
                    def operation():
                        payload = self.client.approve(request_id, [selected])
                        if payload.get("state") == "working" and isinstance(task_id, str):
                            return self.client.run(task_id)
                        return payload

                    self._submit(operation, "Applying approval...")

            def _advance(self):
                task_id = self.current_state.get("task_id")
                if isinstance(task_id, str):
                    self._submit(
                        lambda: self.client.advance(task_id),
                        "Advancing the pet task...",
                    )

            def _retry(self):
                task_id = self.current_state.get("task_id")
                if isinstance(task_id, str):
                    self._submit(lambda: self.client.retry(task_id), "Retrying the pet task...")

            def _open_workspace(self):
                import webbrowser

                webbrowser.open(f"{self.client.base_url}/?lang={self.language}")

        return _Window()


# Keep the old import working while presenting the product as Gleave Desktop.
DesktopWindow = PetWindow
