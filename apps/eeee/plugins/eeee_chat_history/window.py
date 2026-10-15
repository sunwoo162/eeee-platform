"""Mobile-shaped chat surface for the separately installed EEEE plugin."""

from __future__ import annotations

from typing import Any


def ChatHistoryWindow(client: Any, *, conversation_id: str = "desktop-default"):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )

    from app.desktop.worker import QtTaskRunner

    class _ChatHistoryWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.client = client
            self.conversation_id = conversation_id.strip() or "desktop-default"
            self._busy = False
            self._turns: list[dict[str, object]] = []
            self._next_before_id: int | None = None
            self._task_runner = QtTaskRunner(parent=self)
            self.setWindowTitle("EEEE 채팅 기록")
            self.setFixedSize(430, 760)
            self.setStyleSheet(
                "QWidget { background: #11131a; color: #f4f5fb; }"
                "QListWidget, QLineEdit { background: #1b1e28; border: 1px solid #34394a;"
                " border-radius: 12px; padding: 8px; }"
                "QPushButton { background: #f3a35b; color: #19130f; border: 0;"
                " border-radius: 12px; padding: 10px 14px; font-weight: 700; }"
                "QPushButton:disabled { background: #555965; color: #a7abb9; }"
            )

            root = QVBoxLayout(self)
            root.setContentsMargins(16, 16, 16, 16)
            root.setSpacing(10)

            header = QHBoxLayout()
            title = QLabel("EEEE 채팅 기록")
            title.setStyleSheet("font-size: 20px; font-weight: 700;")
            header.addWidget(title)
            header.addStretch(1)
            self.refresh_button = QPushButton("새로고침")
            self.refresh_button.clicked.connect(self._refresh_conversations)
            header.addWidget(self.refresh_button)
            root.addLayout(header)

            self.conversation_list = QListWidget()
            self.conversation_list.setMaximumHeight(108)
            self.conversation_list.currentItemChanged.connect(self._conversation_selected)
            root.addWidget(self.conversation_list)

            self.transcript_scroll = QScrollArea()
            self.transcript_scroll.setWidgetResizable(True)
            self.transcript_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            self.transcript = QWidget()
            self.transcript_layout = QVBoxLayout(self.transcript)
            self.transcript_layout.setContentsMargins(4, 8, 4, 8)
            self.transcript_layout.setSpacing(10)
            self.transcript_layout.addStretch(1)
            self.transcript_scroll.setWidget(self.transcript)
            root.addWidget(self.transcript_scroll, 1)

            self.older_button = QPushButton("이전 기록 불러오기")
            self.older_button.setVisible(False)
            self.older_button.clicked.connect(self._load_older)
            root.addWidget(self.older_button)

            self.status = QLabel("EEEE와의 대화 기록을 불러오는 중이야.")
            self.status.setStyleSheet("color: #9ba3bd; padding: 2px;")
            self.status.setWordWrap(True)
            root.addWidget(self.status)

            input_row = QHBoxLayout()
            self.input = QLineEdit()
            self.input.setPlaceholderText("EEEE에게 명령 보내기")
            self.input.returnPressed.connect(self._send)
            input_row.addWidget(self.input, 1)
            self.send_button = QPushButton("보내기")
            self.send_button.clicked.connect(self._send)
            input_row.addWidget(self.send_button)
            root.addLayout(input_row)
            self._refresh_conversations()

        def _submit(self, operation, on_success, on_error):
            if self._busy:
                return False
            self._busy = True
            self.refresh_button.setEnabled(False)
            self.send_button.setEnabled(False)

            def success(result):
                self._busy = False
                self.refresh_button.setEnabled(True)
                self.send_button.setEnabled(True)
                on_success(result)

            def failure(error):
                self._busy = False
                self.refresh_button.setEnabled(True)
                self.send_button.setEnabled(True)
                on_error(error)

            self._task_runner.submit(operation, success, failure)
            return True

        def _refresh_conversations(self):
            getter = getattr(self.client, "get_conversations", None)
            if not callable(getter):
                self.status.setText("채팅 기록 API를 사용할 수 없어.")
                return
            self._submit(
                lambda: getter(limit=50),
                self._apply_conversations,
                lambda error: self.status.setText(f"기록을 불러오지 못했어: {error}"),
            )

        def _apply_conversations(self, conversations: object):
            rows = [item for item in conversations if isinstance(item, dict)] if isinstance(conversations, list) else []
            self.conversation_list.blockSignals(True)
            self.conversation_list.clear()
            selected = None
            for conversation in rows:
                item = QListWidgetItem(
                    f"{conversation.get('conversationId', '')} · "
                    f"{conversation.get('preview', '')}"
                )
                item.setData(Qt.ItemDataRole.UserRole, str(conversation.get("conversationId", "")))
                self.conversation_list.addItem(item)
                if item.data(Qt.ItemDataRole.UserRole) == self.conversation_id:
                    selected = item
            if selected is None and rows:
                selected = self.conversation_list.item(0)
                self.conversation_id = str(selected.data(Qt.ItemDataRole.UserRole) or self.conversation_id)
            if selected is not None:
                self.conversation_list.setCurrentItem(selected)
            self.conversation_list.blockSignals(False)
            self._load_conversation()

        def _conversation_selected(self, current, _previous):
            if current is None:
                return
            value = current.data(Qt.ItemDataRole.UserRole)
            if isinstance(value, str) and value.strip():
                self.conversation_id = value
                self._load_conversation()

        def _load_conversation(self):
            getter = getattr(self.client, "get_conversation", None)
            if not callable(getter):
                return
            self._submit(
                lambda: getter(self.conversation_id, limit=100),
                self._apply_conversation,
                lambda error: self.status.setText(f"대화를 불러오지 못했어: {error}"),
            )

        def _apply_conversation(self, payload: object):
            turns = payload.get("turns", []) if isinstance(payload, dict) else []
            self._turns = [turn for turn in turns if isinstance(turn, dict)] if isinstance(turns, list) else []
            self._next_before_id = (
                int(payload["nextBeforeId"])
                if isinstance(payload, dict) and payload.get("nextBeforeId") is not None
                else None
            )
            self._render_turns()
            self.status.setText(f"{len(self._turns)}개 메시지 · {self.conversation_id}")
            QTimer.singleShot(0, self._scroll_to_bottom)

        def _load_older(self):
            if self._next_before_id is None:
                return
            getter = getattr(self.client, "get_conversation", None)
            if not callable(getter):
                return
            cursor = self._next_before_id
            self._submit(
                lambda: getter(self.conversation_id, limit=100, before_id=cursor),
                self._prepend_conversation,
                lambda error: self.status.setText(f"이전 기록을 불러오지 못했어: {error}"),
            )

        def _prepend_conversation(self, payload: object):
            older = payload.get("turns", []) if isinstance(payload, dict) else []
            older_turns = [turn for turn in older if isinstance(turn, dict)] if isinstance(older, list) else []
            self._turns = older_turns + self._turns
            self._next_before_id = (
                int(payload["nextBeforeId"])
                if isinstance(payload, dict) and payload.get("nextBeforeId") is not None
                else None
            )
            self._render_turns()
            self.status.setText(f"{len(self._turns)}개 메시지 · {self.conversation_id}")

        def _render_turns(self):
            self._clear_transcript()
            for turn in self._turns:
                self._add_bubble(str(turn.get("role", "assistant")), str(turn.get("content", "")))
            self.transcript_layout.addStretch(1)
            self.older_button.setVisible(self._next_before_id is not None)

        def _clear_transcript(self):
            while self.transcript_layout.count():
                item = self.transcript_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                layout = item.layout()
                if layout is not None:
                    while layout.count():
                        child = layout.takeAt(0)
                        child_widget = child.widget()
                        if child_widget is not None:
                            child_widget.deleteLater()

        def _add_bubble(self, role: str, content: str):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            bubble = QLabel(content)
            bubble.setWordWrap(True)
            bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            bubble.setMaximumWidth(300)
            if role == "user":
                bubble.setStyleSheet(
                    "background: #f3a35b; color: #21170f; border-radius: 14px; padding: 10px;"
                )
                row.addStretch(1)
                row.addWidget(bubble)
            else:
                bubble.setStyleSheet(
                    "background: #2a2f3c; color: #f4f5fb; border-radius: 14px; padding: 10px;"
                )
                row.addWidget(bubble)
                row.addStretch(1)
            self.transcript_layout.addLayout(row)

        def _send(self):
            text = self.input.text().strip()
            if not text:
                return
            sender = getattr(self.client, "send_conversation_message", None)
            if not callable(sender):
                self.status.setText("EEEE 명령 API를 사용할 수 없어.")
                return
            self.input.clear()
            self.status.setText("EEEE가 생각하는 중이야…")
            self._submit(
                lambda: sender(text, conversation_id=self.conversation_id),
                lambda _result: self._refresh_conversations(),
                lambda error: self.status.setText(f"보내지 못했어: {error}"),
            )

        def _scroll_to_bottom(self):
            bar = self.transcript_scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

        def closeEvent(self, event):
            self._task_runner.shutdown()
            super().closeEvent(event)

    return _ChatHistoryWindow()
