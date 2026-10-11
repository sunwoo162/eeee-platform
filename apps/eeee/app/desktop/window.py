"""PySide6 desktop companion window."""

from pathlib import Path
import time

from app.desktop.client import PetApiClient
from app.desktop.presentation import PetPresentation
from app.desktop.session import DesktopSession
from app.desktop.worker import QtTaskRunner
from app.assistant.profile import DEFAULT_PROFILE, load_profile, save_profile


def _force_windows_topmost(widget) -> None:
    """Reassert TOPMOST for the pet after another Windows app gains focus."""
    import sys

    if sys.platform != "win32" or not widget.isVisible():
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        ctypes.windll.user32.SetWindowPos(
            hwnd,
            -1,  # HWND_TOPMOST
            0,
            0,
            0,
            0,
            0x0001 | 0x0002 | 0x0040,  # NOSIZE | NOMOVE | SHOWWINDOW
        )
    except (AttributeError, OSError, TypeError, ValueError):
        # Qt's WindowStaysOnTopHint remains the portable fallback.
        return


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
        "assistant_busy": "잠깐만, 생각하는 중이야…",
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
        "assistant_busy": "One moment, I’m thinking…",
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


# Virtual-key codes grouped by physical QWERTY position.  The boundary is
# between T/Y, G/H, and B/N, matching the user's left/right keyboard split.
_LEFT_HAND_KEY_CODES = frozenset(
    {
        *range(0x31, 0x36),  # 1-5
        0x51, 0x57, 0x45, 0x52, 0x54,  # QWERT
        0x41, 0x53, 0x44, 0x46, 0x47,  # ASDFG
        0x5A, 0x58, 0x43, 0x56, 0x42,  # ZXCVB
        0x09, 0x14,  # Tab, Caps Lock
        0x70, 0x71, 0x72, 0x73, 0x74,  # F1-F5
        0xA0, 0xA2, 0xA4,  # Left Shift/Ctrl/Alt
    }
)
_RIGHT_HAND_KEY_CODES = frozenset(
    {
        0x36, 0x37, 0x38, 0x39, 0x30,  # 6-0
        0x59, 0x55, 0x49, 0x4F, 0x50,  # YUIOP
        0x48, 0x4A, 0x4B, 0x4C,  # HJKL
        0x4E, 0x4D,  # NM
        0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0,  # punctuation
        0xDB, 0xDC, 0xDD, 0xDE,
        0x08, 0x0D,  # Backspace, Enter
        0x75, 0x76, 0x77, 0x78, 0x79, 0x7A, 0x7B,  # F6-F12
        0xA1, 0xA3, 0xA5,  # Right Shift/Ctrl/Alt
    }
)


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
            from PySide6.QtCore import QEvent, QPoint, QRect, QSettings, QSize, QTimer, Qt
            from PySide6.QtGui import QAction, QColor, QCursor, QFont, QPainter, QPixmap
            from PySide6.QtWidgets import (
                QComboBox,
                QFrame,
                QHBoxLayout,
                QInputDialog,
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
                self._pet_drag_origin = None
                self._pet_window_origin = None
                self._pet_is_dragging = False
                self._busy = False
                self._refreshing = False
                self._auth_login_in_progress = False
                self._closing = False
                self._quit_requested = False
                self._app = QApplication.instance()
                self._tray = None
                self._workspace = None
                self._task_runner = QtTaskRunner(parent=self)
                self._settings = QSettings("Gleave", "GleaveDesktop")
                saved_language = self._settings.value("language", "ko")
                self.language = saved_language if saved_language in _DESKTOP_TEXT else "ko"
                self.profile_name = str(self._settings.value("profileName", "EEEE")) or "EEEE"
                self.profile_avatar = str(self._settings.value("profileAvatar", "🐾")) or "🐾"
                self.setObjectName("desktopCompanion")
                self.setWindowTitle(self._text("window_title"))
                self.setWindowFlags(
                    Qt.WindowType.FramelessWindowHint
                    | Qt.WindowType.WindowStaysOnTopHint
                    | Qt.WindowType.Tool
                )
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                # Pet mode is intentionally a transparent, compact overlay.
                # The conversation surface owns the card background; the pet
                # itself must never look like a large dark application window.
                self.setAutoFillBackground(False)
                self.setMinimumWidth(96)
                self.setMaximumWidth(760)

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

                # Keep the always-on-top pet unobtrusive; the speech bubble and
                # quick composer provide the readable surface around it.
                # Keep the pet itself physically stable.  Speech bubbles and
                # the detached composer may grow, but the character never
                # changes size when a different frame is selected.
                self._pet_display_size = QSize(180, 108)
                asset_dir = Path(__file__).resolve().parent / "assets"
                self._pet_pixmaps = {
                    frame: QPixmap(str(asset_dir / filename))
                    for frame, filename in {
                        "idle": "cat-keyboard-idle.png",
                        # The visual source files are named by their legacy
                        # export direction; user input direction is the
                        # opposite, so keep the mapping explicit here.
                        "left": "cat-keyboard-right.png",
                        "right": "cat-keyboard-left.png",
                        "left_alt": "cat-keyboard-right-alt.png",
                        "right_alt": "cat-keyboard-left-alt.png",
                        "gaze_left": "cat-keyboard-gaze-left.png",
                        "gaze_right": "cat-keyboard-gaze-right.png",
                    }.items()
                }
                # Every generated frame has a different amount of transparent
                # padding.  Scaling the raw files directly makes the cat jump
                # in size whenever gaze/typing changes.  Use one shared alpha
                # crop for every frame so the visible mascot keeps one stable
                # footprint on screen.
                # The bundled frames are exported on one 1672x941 canvas. A
                # shared crop keeps the visible mascot stable without doing a
                # slow per-pixel alpha scan during application startup.
                self._pet_source_rect = QRect(144, 104, 1301, 837)
                self._last_rendered_frame = "idle"
                self._typing_pose = {"pressing": None, "lifted": None}
                self._typing_active = False
                self._typing_frame = 0
                self._typing_hand = "left"
                self._last_text_edit_at = 0.0
                self._last_typing_frame: str | None = None
                self._last_gaze_frame = "idle"
                self._gaze_offset = (0, 0)
                self._last_gaze_offset = (0, 0)
                self._global_key_states: dict[int, bool] = {}
                self._global_key_press_events: list[int] = []
                self._typing_event_count = 0
                self._typing_hand_press_count = 0
                self._last_global_key_code: int | None = None
                self.character = QLabel()
                self.character.setObjectName("assistantCharacter")
                self.character.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.character.setFont(QFont("Segoe UI Emoji", 34))
                self.character.installEventFilter(self)
                self.character.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                self.character.customContextMenuRequested.connect(self._show_pet_menu)
                self._set_pet_frame("idle")
                root.addWidget(self.character)

                self.headline = QLabel()
                self.headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.headline.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
                root.addWidget(self.headline)

                self.detail = QLabel()
                self.detail.setObjectName("assistantBubble")
                self.detail.setWordWrap(True)
                self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.detail.setMinimumWidth(240)
                self.detail.setMaximumWidth(640)
                root.addWidget(self.detail)

                # Visual order: AI speech bubble -> pet -> composer below.
                # The bubble must not sit underneath the pet or get separated
                # from the composer by the window's invisible legacy widgets.
                root.removeWidget(self.character)
                root.removeWidget(self.detail)
                root.insertWidget(0, self.detail)
                root.insertWidget(1, self.character)

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
                # Quick Chat is a separate lightweight tool window.  The pet
                # remains the always-visible host; this surface owns only the
                # conversation controls and can be hidden independently.
                self.command_surface.setObjectName("quickChat")
                self.command_surface.setWindowFlags(
                    Qt.WindowType.FramelessWindowHint
                    | Qt.WindowType.WindowStaysOnTopHint
                    | Qt.WindowType.Tool
                )
                self.command_surface.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                # Keep Quick Chat compact enough to feel attached to the pet.
                # Without a width cap, Qt lets a long response expand the
                # tool window and pushes it far away from the character.
                self.command_surface.setFixedWidth(340)
                command_layout = QVBoxLayout(self.command_surface)
                command_layout.setContentsMargins(14, 14, 14, 14)
                self.quick_status = QLabel()
                self.quick_status.setObjectName("quickStatus")
                self.quick_status.setWordWrap(True)
                command_layout.addWidget(self.quick_status)
                self.quick_reply = QLabel()
                self.quick_reply.setObjectName("quickReply")
                self.quick_reply.setWordWrap(True)
                command_layout.addWidget(self.quick_reply)
                assistant_row = QHBoxLayout()
                self.assistant_input = QLineEdit()
                self.assistant_input.setObjectName("assistantComposer")
                self.assistant_input.setMinimumWidth(190)
                self.assistant_input.setMaximumWidth(210)
                self.assistant_input.installEventFilter(self)
                self.assistant_button = QPushButton()
                self.assistant_button.setObjectName("primaryAction")
                self.assistant_button.setFixedWidth(108)
                self.assistant_button.clicked.connect(self._route_assistant)
                self.assistant_input.returnPressed.connect(self._route_assistant)
                self.assistant_input.textEdited.connect(self._on_user_typing)
                assistant_row.addWidget(self.assistant_input)
                assistant_row.addWidget(self.assistant_button)
                command_layout.addLayout(assistant_row)
                self.command_surface.installEventFilter(self)
                self._app.installEventFilter(self)

                self._reply_hide_timer = QTimer(self)
                self._reply_hide_timer.setSingleShot(True)
                self._reply_hide_timer.setInterval(8000)
                self._reply_hide_timer.timeout.connect(self._hide_reply_bubble)
                self._typing_timer = QTimer(self)
                self._typing_timer.setInterval(24)
                self._typing_timer.timeout.connect(self._advance_reply_typing)
                self._typing_text = ""
                self._typing_index = 0
                self._pet_motion_timer = QTimer(self)
                # 16 ms keeps mouse gaze and key-down animation responsive
                # without tying animation to the slower API refresh timer.
                self._pet_motion_timer.setInterval(16)
                self._pet_motion_timer.timeout.connect(self._update_pet_motion)
                self._pet_motion_timer.start()

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
                self.quick_status.hide()
                self.quick_reply.hide()

                self.setStyleSheet(
                    "#desktopCompanion { background: transparent; border: none; "
                    "color: #f4f3fb; }"
                    "#desktopCompanion QLabel { background: transparent; border: none; "
                    "color: #f4f3fb; }"
                    "#assistantCharacter { padding: 4px; }"
                    "#assistantBubble { background: #fff7ef; border: 2px solid #efc28f; "
                    "border-radius: 24px; padding: 12px 18px; color: #33281f; }"
                    "#projectStatusCard { background: #202332; border: 1px solid #373c53; "
                    "border-radius: 14px; }"
                    "#projectStatus { color: #ffffff; font-weight: 600; }"
                    "#runtimeStatus, #trustStatus, #mobileStatus { color: #b9bdd0; font-size: 11px; }"
                    "#desktopCompanion QLineEdit, #desktopCompanion QComboBox { "
                    "background: #fffaf5; padding: 10px 13px; border: 2px solid #efc28f; "
                    "border-radius: 20px; color: #33281f; selection-background-color: #f4c58e; }"
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
                self.command_surface.setStyleSheet(
                    "#quickChat { background: transparent; border: none; color: #33281f; }"
                    "#quickChat QLabel { background: transparent; border: none; color: #f4f3fb; }"
                    "#quickStatus { color: #b9bdd0; font-size: 11px; }"
                    "#quickReply { background: #fff7ef; border: 2px solid #efc28f; "
                    "border-radius: 24px; padding: 11px 15px; color: #33281f; }"
                    "#quickChat QLineEdit { background: #fffaf5; padding: 10px 13px; "
                    "border: 2px solid #efc28f; border-radius: 20px; color: #33281f; }"
                    "#quickChat QPushButton { background: #f1a65a; padding: 10px 12px; "
                    "border: 2px solid #efc28f; border-radius: 20px; color: #33281f; font-weight: 600; }"
                )
                self._apply_language()
                self._timer = QTimer(self)
                self._timer.timeout.connect(self._background_refresh)
                self._topmost_timer = QTimer(self)
                self._topmost_timer.setInterval(1000)
                self._topmost_timer.timeout.connect(self._enforce_topmost)
                self._topmost_timer.start()
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
                    event.type() == QEvent.Type.MouseButtonPress
                    and command_surface is not None
                    and command_surface.isVisible()
                ):
                    global_pos = event.globalPosition().toPoint()
                    if self._handle_global_mouse_press(global_pos):
                        return False
                if (
                    watched in (assistant_input, command_surface)
                    and event.type() == QEvent.Type.KeyPress
                    and event.key() == Qt.Key.Key_Escape
                ):
                    self.hide_command_surface()
                    return True
                if (
                    watched is assistant_input
                    and event.type() == QEvent.Type.KeyPress
                    and event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape)
                ):
                    key_code = int(event.nativeVirtualKey() or event.key())
                    self._register_key_press(key_code)
                if (
                    watched is self.character
                    and event.type() == QEvent.Type.MouseButtonPress
                    and event.button() == Qt.MouseButton.LeftButton
                ):
                    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        self._open_workspace()
                        return True
                    self._pet_drag_origin = event.globalPosition().toPoint()
                    self._pet_window_origin = self.pos()
                    self._pet_is_dragging = False
                    return True
                if watched is self.character and event.type() == QEvent.Type.MouseMove:
                    if self._pet_drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
                        current = event.globalPosition().toPoint()
                        if not self._pet_is_dragging:
                            distance = (current - self._pet_drag_origin).manhattanLength()
                            self._pet_is_dragging = distance >= QApplication.startDragDistance()
                        if self._pet_is_dragging and self._pet_window_origin is not None:
                            self.move(self._pet_window_origin + current - self._pet_drag_origin)
                        return True
                if (
                    watched is self.character
                    and event.type() == QEvent.Type.MouseButtonRelease
                    and event.button() == Qt.MouseButton.LeftButton
                ):
                    was_dragging = self._pet_is_dragging
                    self._pet_drag_origin = None
                    self._pet_window_origin = None
                    self._pet_is_dragging = False
                    if not was_dragging:
                        self.show_command_surface()
                    return True
                return super().eventFilter(watched, event)

            def showEvent(self, event):
                super().showEvent(event)
                # WindowStaysOnTopHint is the policy; raising after the native
                # window is shown makes that policy reliable on Windows when
                # another app was focused immediately before the pet opened.
                self.raise_()
                QTimer.singleShot(0, self.raise_)
                QTimer.singleShot(0, self._enforce_topmost)

            def _enforce_topmost(self):
                _force_windows_topmost(self)
                if self.command_surface.isVisible():
                    _force_windows_topmost(self.command_surface)

            def show_command_surface(self):
                # The pet bubble remains the only response surface. Quick
                # Chat is only the composer anchored below the pet.
                self.detail.show()
                self._reply_hide_timer.stop()
                self.command_surface.show()
                self.command_surface.adjustSize()
                self.command_surface.move(self._command_surface_position())
                QTimer.singleShot(0, self._reposition_command_surface)
                self.quick_reply.hide()
                self.raise_()
                self.command_surface.raise_()
                self.command_surface.activateWindow()
                self._enforce_topmost()
                self.assistant_input.setFocus()

            def _reposition_command_surface(self):
                if self.command_surface.isVisible():
                    self.command_surface.move(self._command_surface_position())
                    self._enforce_topmost()

            def resizeEvent(self, event):
                super().resizeEvent(event)
                self._reposition_command_surface()

            def moveEvent(self, event):
                super().moveEvent(event)
                self._reposition_command_surface()

            def hide_command_surface(self):
                self.command_surface.hide()
                self.quick_reply.hide()
                self.detail.show()
                self._schedule_reply_hide()
                self.clearFocus()

            def _pet_anchor_rect(self):
                """Return the complete visible pet bounds in screen coordinates."""
                return self.frameGeometry()

            def _command_surface_position(self, screen_rect=None, surface_size=None):
                """Place Quick Chat next to the pet, clamped to the usable screen."""
                margin = 12
                anchor = self._pet_anchor_rect()
                if screen_rect is None:
                    screen = self.screen()
                    if screen is None:
                        screen = QApplication.primaryScreen()
                    screen_rect = screen.availableGeometry()
                if surface_size is None:
                    surface_size = self.command_surface.size()

                min_x = screen_rect.left() + margin
                max_x = screen_rect.right() - margin - surface_size.width() + 1
                min_y = screen_rect.top() + margin
                max_y = screen_rect.bottom() - margin - surface_size.height() + 1

                centered_x = anchor.center().x() - surface_size.width() // 2
                x = max(min_x, min(centered_x, max_x))
                below_y = anchor.bottom() + margin
                above_y = anchor.top() - margin - surface_size.height()
                # The composer belongs below the pet. Only move it above when
                # the current monitor has no room underneath.
                y = below_y if below_y <= max_y else above_y
                y = max(min_y, min(y, max_y))
                return QPoint(x, y)

            def _handle_global_mouse_press(self, global_pos):
                if not self.command_surface.isVisible():
                    return False
                if (
                    self.command_surface.frameGeometry().contains(global_pos)
                    or self.frameGeometry().contains(global_pos)
                ):
                    return False
                self.hide_command_surface()
                return True

            def _hide_reply_bubble(self):
                if not self.command_surface.isVisible():
                    self.detail.hide()

            def _source_pixmap_for_frame(self, frame: str):
                """Keep the keyboard fixed while changing only the eyes."""
                base = self._pet_pixmaps.get("idle")
                is_gaze = frame.startswith("gaze_")
                is_press = frame.endswith("_press")
                base_frame = frame.removesuffix("_press")
                is_typing = base_frame in {"left", "right", "left_alt", "right_alt"}
                if not is_gaze and not is_typing:
                    return self._pet_pixmaps.get(frame)
                if is_typing:
                    base = self._pet_pixmaps.get(base_frame)
                if base is None or base.isNull():
                    return base

                press_offset_y = 12 if is_press else 0
                if press_offset_y:
                    pressed = QPixmap(base.size())
                    pressed.fill(Qt.GlobalColor.transparent)
                    press_painter = QPainter(pressed)
                    press_painter.drawPixmap(0, press_offset_y, base)
                    press_painter.end()
                    base = pressed

                rendered = base.copy()
                painter = QPainter(rendered)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#ffffff"))
                eyes = ((721, 455, 28), (1029, 545, 28))
                for x, y, radius in eyes:
                    painter.drawEllipse(QPoint(x, y + press_offset_y), radius, radius)
                offset_x, offset_y = self._gaze_offset
                painter.setBrush(QColor("#111111"))
                for x, y, radius in eyes:
                    painter.drawEllipse(
                        QPoint(x + offset_x, y + press_offset_y + offset_y),
                        radius - 3,
                        radius - 3,
                    )
                painter.end()
                return rendered

            def _set_pet_frame(self, frame: str) -> None:
                pixmap = self._source_pixmap_for_frame(frame)
                if pixmap is None or pixmap.isNull():
                    self.character.setText("🐱")
                    self.character.setFixedSize(self._pet_display_size)
                    return
                # Crop the common transparent margin before scaling.  The
                # QLabel remains fixed, while the artwork occupies the same
                # visual area in idle, gaze, and typing frames.
                visible = pixmap.copy(self._pet_source_rect)
                rendered = visible.scaled(
                    self._pet_display_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                if frame.removesuffix("_press") in {"left", "right", "left_alt", "right_alt"}:
                    pressing = frame.removesuffix("_press").removesuffix("_alt")
                    self._typing_pose = {
                        "pressing": pressing,
                        "lifted": "right" if pressing == "left" else "left",
                    }
                else:
                    self._typing_pose = {"pressing": None, "lifted": None}
                self._last_rendered_frame = frame
                self.character.setPixmap(rendered)
                self.character.setFixedSize(self._pet_display_size)

            def _on_user_typing(self, text: str) -> None:
                self._typing_active = bool(text.strip())
                self._last_text_edit_at = time.monotonic() if text else 0.0
                if not self._typing_active:
                    self._typing_frame = 0
                self._update_pet_motion()

            def _hand_for_key_code(self, code: int) -> str:
                """Map a physical key to its QWERTY hand, preserving neutral keys."""
                if code in _LEFT_HAND_KEY_CODES:
                    return "left"
                if code in _RIGHT_HAND_KEY_CODES:
                    return "right"
                # Space and layout-specific keys have no unique hand. Keep
                # the current side rather than making them flip the mascot.
                return self._typing_hand

            def _register_key_press(self, code: int) -> None:
                hand = self._hand_for_key_code(code)
                if hand == self._typing_hand:
                    self._typing_hand_press_count += 1
                else:
                    self._typing_hand = hand
                    self._typing_hand_press_count = 1
                self._last_typing_frame = self._typing_frame_name()
                self._last_global_key_code = code
                self._typing_active = True
                self._last_text_edit_at = time.monotonic()
                self._typing_event_count += 1

            def _typing_frame_name(self) -> str:
                """Animate the same paw without switching keyboard sides.

                The available ``*_alt`` artwork is a mirrored full-body pose,
                not a second press frame for the same paw. Selecting it for a
                repeated key therefore makes the cat appear to switch hands.
                Use a generated press frame from the same base artwork instead,
                so Korean IME repeats (for example ``ㅇ``/physical D) animate
                while remaining on the left paw.
                """
                suffix = "_press" if self._typing_hand_press_count % 2 == 0 else ""
                return f"{self._typing_hand}{suffix}"

            def _read_global_key_states(self) -> dict[int, bool]:
                """Read currently held keyboard keys without stealing focus."""
                import sys

                if sys.platform != "win32":
                    return {}
                try:
                    import ctypes

                    user32 = ctypes.windll.user32
                    key_codes = list(range(0x30, 0x5B)) + list(range(0x60, 0x70))
                    key_codes += list(range(0xBA, 0xE3)) + [0x08, 0x09, 0x0D, 0x20]
                    states = {}
                    for code in key_codes:
                        raw_state = int(user32.GetAsyncKeyState(code))
                        # The low bit records a press transition since the
                        # previous call.  It is essential for fast repeated
                        # presses where key-up and key-down happen between
                        # two timer polls and the high bit looks unchanged.
                        if raw_state & 0x0001:
                            self._global_key_press_events.append(code)
                        states[code] = bool(raw_state & 0x8000)
                    return states
                except (AttributeError, OSError, TypeError):
                    return {}

            def _apply_global_key_states(self, states: dict[int, bool]) -> None:
                """Apply only newly pressed global keys to the typing state."""
                previous = self._global_key_states
                edge_presses = [
                    code
                    for code, is_down in states.items()
                    if is_down and not previous.get(code, False)
                ]
                transition_presses = list(self._global_key_press_events)
                self._global_key_press_events.clear()
                # Preserve the transition queue exactly: two fast presses of
                # the same key are two poses, not one deduplicated event.
                pressed = transition_presses + [
                    code for code in edge_presses if code not in transition_presses
                ]
                self._global_key_states = states
                if pressed:
                    for code in pressed:
                        self._register_key_press(code)
                elif not any(states.values()):
                    self._typing_active = False

            def _gaze_for_cursor(self, cursor) -> tuple[str, tuple[int, int]]:
                pet_center = self.character.mapToGlobal(self.character.rect().center())
                delta_x = cursor.x() - pet_center.x()
                delta_y = cursor.y() - pet_center.y()
                offset = (
                    max(-16, min(16, round(delta_x / 110))),
                    max(-12, min(12, round(delta_y / 110))),
                )
                if delta_x < -72:
                    frame = "gaze_left"
                elif delta_x > 72:
                    frame = "gaze_right"
                else:
                    frame = "gaze_center"
                return frame, offset

            def _update_pet_motion(self) -> None:
                global_states = self._read_global_key_states()
                self._apply_global_key_states(global_states)
                gaze_frame, gaze_offset = self._gaze_for_cursor(QCursor.pos())
                self._gaze_offset = gaze_offset
                self._last_gaze_frame = gaze_frame
                self._last_gaze_offset = gaze_offset
                if global_states and any(global_states.values()):
                    self._set_pet_frame(self._typing_frame_name())
                    return

                recent_input = (
                    self._last_text_edit_at
                    and time.monotonic() - self._last_text_edit_at < 0.12
                )
                if recent_input:
                    self._typing_active = True
                    self._set_pet_frame(self._typing_frame_name())
                    return

                self._typing_active = False
                # Once the user has typed, keep the last hand pose instead of
                # snapping back to the idle keyboard pose.  The eye overlay
                # still follows the cursor through the current gaze offset.
                self._set_pet_frame(self._last_typing_frame or gaze_frame)

            def _start_reply_typing(self, text: str) -> None:
                self._typing_timer.stop()
                self._typing_text = text
                self._typing_index = 0
                self.detail.setText("")
                self.quick_reply.setText("")
                if not text:
                    return
                self._advance_reply_typing()
                if self._typing_index < len(self._typing_text):
                    self._typing_timer.start()

            def _advance_reply_typing(self) -> None:
                if self._typing_index >= len(self._typing_text):
                    self._typing_timer.stop()
                    self._schedule_reply_hide()
                    return
                self._typing_index += 1
                visible_text = self._typing_text[: self._typing_index]
                self.detail.setText(visible_text)
                self.quick_reply.setText(visible_text)
                if self._typing_index >= len(self._typing_text):
                    self._typing_timer.stop()
                    self._schedule_reply_hide()

            def _schedule_reply_hide(self):
                state = self.current_state.get("state")
                if self.detail.text() and state in {"idle", "completed", "blocked", "failed"}:
                    self._reply_hide_timer.start()
                else:
                    self._reply_hide_timer.stop()

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
                self._reply_hide_timer.stop()
                self._app.removeEventFilter(self)
                self._task_runner.shutdown()
                self.command_surface.close()
                if self._workspace is not None:
                    self._workspace.close()
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

            def _load_profile(self):
                profile_path = self._profile_path()
                profile = load_profile(profile_path)
                # Keep the pre-profile.json settings keys as a one-time
                # migration path for existing desktop installations.
                if not profile_path.exists():
                    legacy = {
                        **profile,
                        "name": str(self._settings.value("profileName", profile["name"])) or profile["name"],
                        "avatar": str(self._settings.value("profileAvatar", profile["avatar"])) or profile["avatar"],
                    }
                    profile = save_profile(profile_path, legacy)
                self.profile_name = profile["name"]
                self.profile_avatar = profile["avatar"]
                self.setWindowTitle(f"{self.profile_name} • Gleave")
                if self._tray is not None:
                    self._tray.setToolTip(f"{self.profile_name} local assistant")

            def _show_pet_menu(self, position):
                menu = QMenu(self)
                profile_action = menu.addAction("펫 프로필 설정" if self.language == "ko" else "Pet profile")
                workspace_action = menu.addAction(self._text("open_workspace"))
                menu.addSeparator()
                quit_action = menu.addAction("종료" if self.language == "ko" else "Quit")
                selected = menu.exec(self.character.mapToGlobal(position))
                if selected is profile_action:
                    self._edit_pet_profile(QInputDialog)
                elif selected is workspace_action:
                    self._open_workspace()
                elif selected is quit_action:
                    self.request_quit()

            def _edit_pet_profile(self, QInputDialog):
                name, accepted = QInputDialog.getText(
                    self,
                    "펫 프로필" if self.language == "ko" else "Pet profile",
                    "이름" if self.language == "ko" else "Name",
                    text=self.profile_name,
                )
                if not accepted or not name.strip():
                    return
                avatars = ["🐾", "🦊", "🐱", "🐶", "🦄", "🤖", "🌟"]
                avatar, accepted = QInputDialog.getItem(
                    self,
                    "펫 프로필" if self.language == "ko" else "Pet profile",
                    "아바타" if self.language == "ko" else "Avatar",
                    avatars,
                    max(0, avatars.index(self.profile_avatar)) if self.profile_avatar in avatars else 0,
                    False,
                )
                if not accepted:
                    return
                self._settings.setValue("profileName", name.strip())
                self._settings.setValue("profileAvatar", avatar)
                save_profile(self._profile_path(), {
                    **load_profile(self._profile_path()),
                    "name": name.strip(),
                    "avatar": avatar,
                })
                self._load_profile()
                if self.current_state.get("state") in {"idle", "completed"}:
                    self._update_pet_motion()

            @staticmethod
            def _profile_path():
                from app.config import Settings

                return Settings().assistant_profile_path

            def _apply_language(self):
                self.setWindowTitle(f"{self.profile_name} • Gleave")
                self.language_label.setText(self._text("language"))
                self.assistant_input.setPlaceholderText(self._text("assistant_placeholder"))
                self.assistant_button.setText(self._text("ask"))
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
                    self.quick_status.setText(busy_message)
                    self._update_controls()

                def success(payload):
                    if self._closing:
                        return
                    if silent:
                        self._refreshing = False
                        self._render_background(payload)
                        return
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
                    if self._payload_requires_chatgpt_login(error):
                        self._open_login_automatically()
                        return
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
                    # The assistant response is the most recent user-facing
                    # event.  Project state is useful background data, but its
                    # stale lifecycle message must never hide a new reply.
                    {**project_state, **payload}
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
                self._update_pet_motion()
                headlines = _DESKTOP_TEXT[self.language]["headline"]
                self.headline.setText(headlines.get(view.state, view.headline))
                detail = view.detail
                if view.state == "idle" and detail == "Ready for a development request":
                    detail = self._text("start_hint")
                self.quick_status.setText(headlines.get(view.state, view.headline))
                self._reply_hide_timer.stop()
                if self.command_surface.isVisible():
                    self.detail.show()
                    self.quick_reply.hide()
                else:
                    self.quick_reply.hide()
                    self.detail.show()
                self._start_reply_typing(detail)
                self._render_desktop_status(payload)
                candidates = payload.get("candidates", [])
                self.candidate_select.clear()
                for candidate in candidates if isinstance(candidates, list) else []:
                    if isinstance(candidate, dict):
                        repository = candidate.get("repository", {})
                        if isinstance(repository, dict) and isinstance(repository.get("full_name"), str):
                            self.candidate_select.addItem(repository["full_name"])
                self._update_controls()

            def _render_background(self, payload: dict[str, object]):
                """Refresh status without overwriting an active conversation."""
                if not isinstance(payload, dict):
                    return
                if "claimLatch" in payload:
                    self.desktop_snapshot = payload
                project_state = payload.get("projectState")
                status_payload = (
                    {**project_state, **payload}
                    if isinstance(project_state, dict)
                    else payload
                )
                self._render_desktop_status(status_payload)

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

                def on_success(payload):
                    self.assistant_input.clear()
                    if self._payload_requires_chatgpt_login(payload):
                        self._open_login_automatically()
                        return
                    self._render(payload)

                self._submit(
                    lambda: self.session.route(text),
                    self._text("assistant_busy"),
                    on_success=on_success,
                )

            def _open_chatgpt_login(self):
                self._open_login_automatically()

            @staticmethod
            def _payload_requires_chatgpt_login(payload) -> bool:
                text = str(payload).lower()
                return any(marker in text for marker in (
                    "authentication is required", "authenticated chatgpt",
                    "chatgpt authentication", "401 unauthorized", "unauthorized",
                    "로그인이 필요", "로그인 필요",
                ))

            def _open_login_automatically(self):
                if self._on_open_chatgpt is None or self._auth_login_in_progress:
                    return
                self._auth_login_in_progress = True
                notice = dict(self.current_state)
                notice.update({
                    "state": "blocked",
                    "message": "ChatGPT 로그인이 필요해. 로그인 창을 자동으로 여는 중이야.",
                })
                self._render(notice)

                def on_success(opened):
                    self._auth_login_in_progress = False
                    updated = dict(self.current_state)
                    updated.update({
                        "state": "idle" if opened else "blocked",
                        "message": (
                            "로그인 후 다시 말해줘. 로그인 창은 백그라운드 연결로 돌아갈 거야."
                            if opened else "ChatGPT 로그인 창을 열지 못했어."
                        ),
                    })
                    self._render(updated)

                self._submit(
                    self._on_open_chatgpt,
                    "로그인 창을 여는 중…",
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
                from app.desktop.workspace import WorkspaceWindow

                if self._workspace is None:
                    self._workspace = WorkspaceWindow(self.client, language=self.language)
                self._workspace.show()
                self._workspace.raise_()
                self._workspace.activateWindow()

        return _Window()


# Keep the old import working while presenting the product as Gleave Desktop.
DesktopWindow = PetWindow
