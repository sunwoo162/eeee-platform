from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageStatus(StrEnum):
    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class RequestState(StrEnum):
    RECEIVED = "received"
    PERSISTED_USER_MESSAGE = "persisted_user_message"
    CLASSIFIED = "classified"
    AWAITING_APPROVAL = "awaiting_approval"
    GENERATING = "generating"
    EXECUTING = "executing"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class Conversation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str = "local-user"
    title: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class ConversationMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    sequence: int
    role: MessageRole
    content: str
    status: MessageStatus
    client_message_id: str | None = None
    request_id: str | None = None
    provider: str | None = None
    model: str | None = None
    error_code: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class AssistantRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    user_message_id: str
    client_message_id: str
    state: RequestState
    parent_request_id: str | None = None
    attempt: int = 1
    selected_provider: str = "auto"
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    interrupted_at: datetime | None = None


class AssistantEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    request_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
