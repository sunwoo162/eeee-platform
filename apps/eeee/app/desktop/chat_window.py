"""Thin Qt conversation surface backed by the EEEE Core API."""

from __future__ import annotations

from typing import Any, Callable

from app.desktop.presentation import BubbleLayout
from app.desktop.session import ConversationSession
from app.desktop.worker import ConversationWorker, QtTaskRunner


class AssistantChatWindow:
    def __new__(
        cls,
        client: Any,
        *,
        parent=None,
        on_result: Callable[[dict[str, object]], None] | None = None,
    ):
        try:
            from PySide6.QtCore import QTimer, Qt, Signal
            from PySide6.QtGui import QFont
            from PySide6.QtWidgets import (
                QHBoxLayout,
                QLabel,
                QLineEdit,
                QPushButton,
                QSizePolicy,
                QVBoxLayout,
                QWidget,
            )
        except ImportError as exc:
            raise RuntimeError("PySide6 is required for the EEEE chat window") from exc

        class _BubbleLabel(QLabel):
            clicked = Signal()

            def mousePressEvent(self, event):
                self.clicked.emit()
                super().mousePressEvent(event)

        class _Chat(QWidget):
            def __init__(self):
                super().__init__(parent)
                self.client = client
                self.on_result = on_result
                self.runner = QtTaskRunner(parent=self)
                self.session = (
                    ConversationSession(client)
                    if all(
                        hasattr(client, name)
                        for name in ("create_conversation", "submit_turn", "stream_request_events")
                    )
                    else None
                )
                self.bubble_layout = BubbleLayout(max_width=380)
                self.conversation_worker = (
                    ConversationWorker(client, self.session) if self.session is not None else None
                )
                self._hide_timer = QTimer(self)
                self._hide_timer.setSingleShot(True)
                self._hide_timer.setInterval(5000)
                self._hide_timer.timeout.connect(self._hide_bubble)
                self.setObjectName("eeeeChatWindow")
                self.setWindowTitle("EEEE")
                self.setFixedWidth(420)
                root = QVBoxLayout(self)
                root.setContentsMargins(20, 18, 20, 20)
                root.setSpacing(12)
                title = QLabel("EEEE")
                title.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
                root.addWidget(title)
                self.status = _BubbleLabel("무엇을 도와드릴까요?")
                self.status.setWordWrap(True)
                self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
                self.status.setMinimumHeight(0)
                self.status.setMaximumHeight(16777215)
                self.status.clicked.connect(self._bubble_clicked)
                root.addWidget(self.status)
                row = QHBoxLayout()
                self.input = QLineEdit()
                self.input.setPlaceholderText("예: Todo 앱 만들어줘")
                self.input.textChanged.connect(self._draft_changed)
                self.send = QPushButton("보내기")
                self.send.clicked.connect(self.submit)
                self.input.returnPressed.connect(self.submit)
                row.addWidget(self.input, 1)
                row.addWidget(self.send)
                root.addLayout(row)
                self.setStyleSheet(
                    "#eeeeChatWindow { background: #20232b; color: #f3f5f8; border: 1px solid #4b5263; border-radius: 16px; }"
                    "QLabel { color: #f3f5f8; }"
                    "#eeeeChatWindow QLabel#eeeeBubble { background: #fff8e8; color: #111111; border: 3px solid #ffb174; border-radius: 28px; padding: 16px 24px; }"
                    "QLineEdit { background: #2b303b; color: #f3f5f8; border: 1px solid #596274; border-radius: 9px; padding: 9px; }"
                    "QPushButton { background: #8f7cff; color: white; border: 0; border-radius: 9px; padding: 9px 12px; }"
                )
                self.status.setObjectName("eeeeBubble")
                self._resize_bubble()

            def _resize_bubble(self):
                geometry = self.bubble_layout.measure(self.status.text())
                self.status.setMinimumWidth(min(geometry.width, self.width() - 40))
                self.status.adjustSize()
                self.adjustSize()

            def _draft_changed(self, value: str):
                if value:
                    self._hide_timer.stop()

            def _hide_bubble(self):
                self.status.hide()

            def _show_bubble(self, text: str):
                self.status.setText(text)
                self.status.show()
                self._resize_bubble()

            def _bubble_clicked(self):
                if self.session is None:
                    return
                if self.session.state not in {"answer", "error", "hidden"}:
                    return
                self.session.begin_input()
                self._show_bubble("")
                self.input.setEnabled(True)
                self.send.setEnabled(True)
                self.input.setFocus()
                self._hide_timer.start()

            def _render_conversation_result(self, result: dict[str, object]):
                messages = result.get("messages")
                answer = None
                if isinstance(messages, list):
                    for message in reversed(messages):
                        if isinstance(message, dict) and message.get("role") == "assistant":
                            answer = message.get("content")
                            break
                if isinstance(answer, str):
                    self._show_bubble(answer)
                else:
                    self._show_bubble("요청을 처리하지 못했어요.")
                self.input.setEnabled(True)
                self.send.setEnabled(True)
                self.input.clear()
                self._hide_timer.start()
                if self.on_result is not None:
                    self.on_result(result)

            def _submit_conversation(self, text: str):
                self._show_bubble(text)
                self.send.setEnabled(False)
                self.input.setEnabled(False)

                def operation():
                    return self.conversation_worker.run_turn(text)

                def success(result):
                    self._render_conversation_result(result)

                def failure(error):
                    self.send.setEnabled(True)
                    self.input.setEnabled(True)
                    self.input.setText(self.session.draft)
                    self._show_bubble(f"요청을 처리하지 못했어요: {error}")
                    self._hide_timer.start()

                self.runner.submit(operation, success, failure)

            def submit(self):
                text = self.input.text().strip()
                if not text or not self.send.isEnabled():
                    return
                if self.session is not None:
                    self._submit_conversation(text)
                    return
                self.send.setEnabled(False)
                self.input.setEnabled(False)
                self.status.setText("EEEE가 작업을 준비하고 있어요…")
                self._resize_bubble()

                def success(result):
                    self.send.setEnabled(True)
                    self.input.setEnabled(True)
                    self.input.clear()
                    route = result.get("assistantRoute") if isinstance(result, dict) else None
                    if route is None and isinstance(result, dict):
                        route = result
                    message = route.get("message") if isinstance(route, dict) else None
                    self._show_bubble(str(message or "요청을 접수했어요. 백그라운드에서 진행합니다."))
                    self._hide_timer.start()
                    if self.on_result is not None and isinstance(result, dict):
                        self.on_result(result)

                def failure(error):
                    self.send.setEnabled(True)
                    self.input.setEnabled(True)
                    self._show_bubble(f"요청을 처리하지 못했어요: {error}")
                    self._hide_timer.start()

                self.runner.submit(
                    lambda: self.client.route_assistant(text, background=True), success, failure
                )

            def closeEvent(self, event):
                self.runner.shutdown()
                super().closeEvent(event)

        return _Chat()
