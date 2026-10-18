"""Lightweight phone-shaped conversation history UI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class _TaskSignals(QObject):
    success = Signal(object)
    failure = Signal(object)


class _Task(QRunnable):
    def __init__(self, operation: Callable[[], object]):
        super().__init__()
        self.operation = operation
        self.signals = _TaskSignals()

    def run(self) -> None:
        try:
            self.signals.success.emit(self.operation())
        except Exception as exc:  # pragma: no cover - emitted back to the UI thread
            self.signals.failure.emit(exc)


class ChatHistoryWindow(QWidget):
    """A separate, bounded chat surface backed by EEEE Core conversation APIs."""

    def __init__(self, client: Any, *, conversation_id: str = "desktop-default"):
        super().__init__()
        self.client = client
        self.conversation_id = conversation_id
        self._next_before_id: int | None = None
        self._turns: list[dict[str, object]] = []
        self._loading = False
        self._active_task: _Task | None = None
        self._pool = QThreadPool.globalInstance()

        self.setWindowTitle("EEEE 채팅 기록")
        self.setFixedSize(430, 760)
        self.setStyleSheet(
            """
            QWidget { background: #15161a; color: #f4f4f5; font-size: 13px; }
            QListWidget, QLineEdit { background: #202126; border: 1px solid #373941; border-radius: 12px; padding: 8px; }
            QListWidget::item { padding: 10px 8px; border-radius: 8px; }
            QListWidget::item:selected { background: #3b3156; }
            QPushButton { background: #8d5bd2; border: 0; border-radius: 10px; padding: 9px 13px; font-weight: 600; }
            QPushButton:disabled { background: #3a3a42; color: #888992; }
            QFrame#userBubble { background: #8d5bd2; border-radius: 14px; }
            QFrame#assistantBubble { background: #292b33; border: 1px solid #3a3c46; border-radius: 14px; }
            QLabel#muted { color: #a8a9b3; }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("채팅 기록")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch(1)
        self.refresh_button = QPushButton("새로고침")
        self.refresh_button.clicked.connect(self._refresh_conversations)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        self.search = QLineEdit()
        self.search.setPlaceholderText("대화 검색")
        self.search.returnPressed.connect(self._refresh_conversations)
        root.addWidget(self.search)

        self.conversations = QListWidget()
        self.conversations.setMaximumHeight(135)
        self.conversations.currentItemChanged.connect(self._conversation_selected)
        root.addWidget(self.conversations)

        self.older_button = QPushButton("이전 메시지 더 보기")
        self.older_button.clicked.connect(self._load_older)
        self.older_button.setVisible(False)
        root.addWidget(self.older_button)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.transcript = QWidget()
        self.transcript_layout = QVBoxLayout(self.transcript)
        self.transcript_layout.setContentsMargins(2, 8, 2, 8)
        self.transcript_layout.setSpacing(8)
        self.transcript_layout.addStretch(1)
        self.scroll.setWidget(self.transcript)
        root.addWidget(self.scroll, 1)

        self.status = QLabel("불러오는 중…")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        composer = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("EEEE에게 메시지 보내기")
        self.input.returnPressed.connect(self._send)
        composer.addWidget(self.input, 1)
        self.send_button = QPushButton("보내기")
        self.send_button.clicked.connect(self._send)
        composer.addWidget(self.send_button)
        root.addLayout(composer)

        self._refresh_conversations()

    def _run(self, operation: Callable[[], object], success: Callable[[object], None]) -> None:
        if self._loading:
            return
        self._loading = True
        task = _Task(operation)
        # Keep the runnable alive until its queued Qt signal is delivered.  A
        # QRunnable may finish before Python's local reference goes away, which
        # otherwise loses the cross-thread completion callback on Windows.
        self._active_task = task
        task.signals.success.connect(lambda value: self._finish_task(success, value))
        task.signals.failure.connect(self._finish_error)
        self._pool.start(task)

    def _finish_task(self, success: Callable[[object], None], value: object) -> None:
        self._loading = False
        self._active_task = None
        success(value)

    def _finish_error(self, error: object) -> None:
        self._loading = False
        self._active_task = None
        self.status.setText(f"불러오지 못했어: {error}")
        self.send_button.setEnabled(True)
        self.refresh_button.setEnabled(True)

    def _refresh_conversations(self) -> None:
        query = self.search.text().strip()
        self.status.setText("대화를 불러오는 중…")
        self.refresh_button.setEnabled(False)
        self._run(
            lambda: self.client.get_conversations(query=query, limit=50),
            self._apply_conversations,
        )

    def _apply_conversations(self, value: object) -> None:
        conversations = value if isinstance(value, list) else []
        selected = self.conversation_id
        self.conversations.blockSignals(True)
        self.conversations.clear()
        selected_item: QListWidgetItem | None = None
        for conversation in conversations:
            if not isinstance(conversation, dict):
                continue
            conversation_id = str(conversation.get("conversationId") or "")
            if not conversation_id:
                continue
            preview = str(conversation.get("preview") or "새 대화")
            count = str(conversation.get("messageCount") or 0)
            item = QListWidgetItem(f"{preview}\n{count}개 메시지")
            item.setData(Qt.ItemDataRole.UserRole, conversation_id)
            self.conversations.addItem(item)
            if conversation_id == selected:
                selected_item = item
        if selected_item is None and self.conversations.count():
            selected_item = self.conversations.item(0)
            selected = str(selected_item.data(Qt.ItemDataRole.UserRole))
        if selected_item is not None:
            self.conversations.setCurrentItem(selected_item)
        self.conversations.blockSignals(False)
        if selected_item is None:
            self._turns = []
            self._render_turns([])
            self.status.setText("저장된 대화가 없어.")
            self.refresh_button.setEnabled(True)
            return
        self.conversation_id = selected
        # Allow any selection notification to settle before starting the detail
        # request.  This keeps the initial list load from racing its transcript.
        QTimer.singleShot(0, self._load_conversation)

    def _conversation_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        conversation_id = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(conversation_id, str) and conversation_id:
            self.conversation_id = conversation_id
            # Let QListWidget finish its selection notification first.  Some Qt
            # versions emit currentItemChanged while signals are being restored;
            # deferring avoids dropping the initial transcript because a second
            # load sees the list request still marked busy.
            QTimer.singleShot(0, self._load_conversation)

    def _load_conversation(self) -> None:
        self.status.setText("메시지를 불러오는 중…")
        self._run(
            lambda: self.client.get_conversation(self.conversation_id, limit=100),
            self._apply_conversation,
        )

    def _load_older(self) -> None:
        if self._next_before_id is None:
            return
        self._run(
            lambda: self.client.get_conversation(
                self.conversation_id, limit=100, before_id=self._next_before_id
            ),
            self._prepend_conversation,
        )

    def _apply_conversation(self, value: object) -> None:
        data = value if isinstance(value, dict) else {}
        turns = data.get("turns", [])
        self._next_before_id = self._optional_int(data.get("nextBeforeId"))
        self._turns = self._normalize_turns(turns if isinstance(turns, list) else [])
        self._render_turns(self._turns)
        self.older_button.setVisible(self._next_before_id is not None)
        self.status.setText("대화 기록")
        self.refresh_button.setEnabled(True)

    def _prepend_conversation(self, value: object) -> None:
        data = value if isinstance(value, dict) else {}
        turns = data.get("turns", [])
        self._next_before_id = self._optional_int(data.get("nextBeforeId"))
        if isinstance(turns, list):
            self._turns = self._normalize_turns(turns) + self._turns
            self._render_turns(self._turns)
        self.older_button.setVisible(self._next_before_id is not None)

    def _render_turns(self, turns: list[object]) -> None:
        while self.transcript_layout.count():
            item = self.transcript_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role") or "assistant")
            content = str(turn.get("content") or "")
            self._add_bubble(role, content)
        self.transcript_layout.addStretch(1)

    @staticmethod
    def _normalize_turns(turns: list[object]) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            normalized.append(
                {
                    "id": turn.get("id"),
                    "role": str(turn.get("role") or "assistant"),
                    "content": str(turn.get("content") or ""),
                    "createdAt": turn.get("createdAt"),
                }
            )
        return normalized

    def _add_bubble(self, role: str, content: str) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        bubble = QFrame()
        bubble.setObjectName("userBubble" if role == "user" else "assistantBubble")
        bubble.setMaximumWidth(340)
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 9, 12, 9)
        label = QLabel(content)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble_layout.addWidget(label)
        if role == "user":
            row.addStretch(1)
        row.addWidget(bubble)
        if role != "user":
            row.addStretch(1)
        self.transcript_layout.insertLayout(max(0, self.transcript_layout.count() - 1), row)

    def _send(self) -> None:
        text = self.input.text().strip()
        if not text or self._loading:
            return
        self.input.clear()
        self.send_button.setEnabled(False)
        self.status.setText("EEEE가 답변하는 중…")
        self._run(
            lambda: self.client.send_conversation_message(text, conversation_id=self.conversation_id),
            lambda result: self._send_finished(text, result),
        )

    def _send_finished(self, text: str, result: object) -> None:
        self.send_button.setEnabled(True)
        self._turns.append({"role": "user", "content": text})
        self._add_bubble("user", text)
        if isinstance(result, dict):
            message = result.get("message")
            if isinstance(message, str) and message:
                self._turns.append({"role": "assistant", "content": message})
                self._add_bubble("assistant", message)
        self.status.setText("전송됨")
        self._refresh_conversations()

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
