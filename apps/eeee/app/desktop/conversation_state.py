"""Small, Qt-free state policy for EEEE Quick Chat."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConversationPhase(str, Enum):
    HIDDEN = "hidden"
    INPUT = "input"
    PROCESSING = "processing"
    TYPING = "typing"
    REPLY = "reply"


@dataclass
class ConversationState:
    """Track user-facing conversation state independently from project status."""

    phase: ConversationPhase = ConversationPhase.HIDDEN
    draft: str = ""
    message: str = ""

    def open_input(self) -> None:
        self.phase = ConversationPhase.INPUT
        self.draft = ""
        self.message = ""

    def update_draft(self, text: str) -> None:
        self.phase = ConversationPhase.INPUT
        self.draft = text
        self.message = ""

    def begin_processing(self) -> None:
        self.phase = ConversationPhase.PROCESSING
        self.draft = ""

    def begin_typing(self) -> None:
        self.phase = ConversationPhase.TYPING

    def finish_reply(self, message: str) -> None:
        self.phase = ConversationPhase.REPLY
        self.draft = ""
        self.message = message

    def hide(self) -> None:
        self.phase = ConversationPhase.HIDDEN
        self.draft = ""

    def can_expire(self) -> bool:
        if self.phase is ConversationPhase.INPUT:
            return not self.draft.strip()
        if self.phase is ConversationPhase.REPLY:
            return bool(self.message.strip())
        return False
