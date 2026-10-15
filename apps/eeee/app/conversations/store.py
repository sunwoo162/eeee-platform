from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.conversations.models import (
    AssistantEvent,
    AssistantRequest,
    Conversation,
    ConversationMessage,
    MessageRole,
    MessageStatus,
    RequestState,
)
from app.conversations.state import validate_request_transition


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class ConversationStore:
    def __init__(self, store) -> None:
        self.store = store

    def create_conversation(self, title: str = "새 대화") -> Conversation:
        now = _now()
        conversation = Conversation(
            id=f"conversation-{uuid4().hex}",
            title=title.strip() or "새 대화",
            created_at=now,
            updated_at=now,
        )
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at, archived_at) "
                "VALUES (?, ?, ?, ?, NULL)",
                (conversation.id, conversation.title, _iso(now), _iso(now)),
            )
        return conversation

    def get_conversation(self, conversation_id: str) -> Conversation:
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Conversation not found: {conversation_id}")
        return Conversation(
            id=row["id"],
            title=row["title"],
            created_at=_datetime(row["created_at"]),
            updated_at=_datetime(row["updated_at"]),
            archived_at=_datetime(row["archived_at"]),
        )

    def list_conversations(self, *, limit: int = 50) -> list[Conversation]:
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM conversations WHERE archived_at IS NULL "
                "ORDER BY updated_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            Conversation(
                id=row["id"],
                title=row["title"],
                created_at=_datetime(row["created_at"]),
                updated_at=_datetime(row["updated_at"]),
                archived_at=_datetime(row["archived_at"]),
            )
            for row in rows
        ]

    def get_messages(
        self, conversation_id: str, *, after_sequence: int = 0, limit: int = 100
    ) -> list[ConversationMessage]:
        if after_sequence < 0 or limit < 1:
            raise ValueError("after_sequence must be nonnegative and limit must be positive")
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE conversation_id = ? AND sequence > ? "
                "ORDER BY sequence ASC LIMIT ?",
                (conversation_id, after_sequence, limit),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def get_message(self, message_id: str) -> ConversationMessage:
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Message not found: {message_id}")
        return _message_from_row(row)

    def add_message(
        self,
        conversation_id: str,
        *,
        role: MessageRole,
        content: str,
        status: MessageStatus = MessageStatus.PENDING,
        client_message_id: str | None = None,
        request_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        error_code: str | None = None,
    ) -> ConversationMessage:
        if not content.strip() and role != MessageRole.ASSISTANT:
            raise ValueError("message content must not be empty")
        now = _now()
        with self.store._connect() as connection:
            conversation = connection.execute(
                "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if conversation is None:
                raise KeyError(f"Conversation not found: {conversation_id}")
            if client_message_id is not None:
                prior = connection.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? AND client_message_id = ?",
                    (conversation_id, client_message_id),
                ).fetchone()
                if prior is not None:
                    if prior["content"] != content or prior["role"] != role.value:
                        raise ValueError("client_message_id was reused with different message content")
                    return _message_from_row(prior)
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            completed_at = _iso(now) if status in {
                MessageStatus.COMPLETED,
                MessageStatus.FAILED,
                MessageStatus.CANCELLED,
                MessageStatus.INTERRUPTED,
            } else None
            message_id = f"message-{uuid4().hex}"
            connection.execute(
                "INSERT INTO messages (id, conversation_id, sequence, role, content, status, "
                "client_message_id, request_id, provider, model, error_code, created_at, completed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id, conversation_id, sequence, role.value, content, status.value,
                    client_message_id, request_id, provider, model, error_code, _iso(now), completed_at,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (_iso(now), conversation_id),
            )
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        return _message_from_row(row)

    def update_message(
        self,
        message_id: str,
        *,
        content: str,
        status: MessageStatus,
        error_code: str | None = None,
    ) -> ConversationMessage:
        now = _now()
        terminal = {
            MessageStatus.COMPLETED,
            MessageStatus.FAILED,
            MessageStatus.CANCELLED,
            MessageStatus.INTERRUPTED,
        }
        with self.store._connect() as connection:
            connection.execute(
                "UPDATE messages SET content = ?, status = ?, error_code = ?, completed_at = ? "
                "WHERE id = ?",
                (
                    content, status.value, error_code,
                    _iso(now) if status in terminal else None,
                    message_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Message not found: {message_id}")
        return _message_from_row(row)

    def create_request(
        self, conversation_id: str, user_message_id: str, client_message_id: str,
        *, parent_request_id: str | None = None, attempt: int = 1,
    ) -> AssistantRequest:
        now = _now()
        request = AssistantRequest(
            id=f"request-{uuid4().hex}",
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            client_message_id=client_message_id,
            state=RequestState.RECEIVED,
            parent_request_id=parent_request_id,
            attempt=attempt,
            created_at=now,
            updated_at=now,
        )
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO assistant_requests (id, conversation_id, user_message_id, "
                "client_message_id, state, parent_request_id, attempt, error_code, created_at, "
                "updated_at, completed_at, interrupted_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL)",
                (
                    request.id, conversation_id, user_message_id, client_message_id,
                    request.state.value, parent_request_id, attempt, _iso(now), _iso(now),
                ),
            )
        return request

    def find_request_by_client_message(
        self, conversation_id: str, client_message_id: str
    ) -> AssistantRequest | None:
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assistant_requests WHERE conversation_id = ? "
                "AND client_message_id = ? ORDER BY attempt DESC LIMIT 1",
                (conversation_id, client_message_id),
            ).fetchone()
        return _request_from_row(row) if row is not None else None

    def get_request(self, request_id: str) -> AssistantRequest:
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assistant_requests WHERE id = ?", (request_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Assistant request not found: {request_id}")
        return _request_from_row(row)

    def transition_request(
        self, request_id: str, target: RequestState, *, error_code: str | None = None
    ) -> AssistantRequest:
        current = self.get_request(request_id)
        validate_request_transition(current.state, target)
        now = _now()
        terminal = {
            RequestState.COMPLETED,
            RequestState.FAILED,
            RequestState.CANCELLED,
            RequestState.INTERRUPTED,
        }
        with self.store._connect() as connection:
            connection.execute(
                "UPDATE assistant_requests SET state = ?, error_code = ?, updated_at = ?, "
                "completed_at = ?, interrupted_at = ? WHERE id = ?",
                (
                    target.value, error_code, _iso(now),
                    _iso(now) if target in terminal else None,
                    _iso(now) if target == RequestState.INTERRUPTED else None,
                    request_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM assistant_requests WHERE id = ?", (request_id,)
            ).fetchone()
        return _request_from_row(row)

    def append_event(
        self, request_id: str, event_type: str, payload: dict[str, Any]
    ) -> AssistantEvent:
        now = _now()
        event = AssistantEvent(
            event_id=f"event-{uuid4().hex}", request_id=request_id, sequence=0,
            event_type=event_type, payload=payload, created_at=now,
        )
        with self.store._connect() as connection:
            request = connection.execute(
                "SELECT id FROM assistant_requests WHERE id = ?", (request_id,)
            ).fetchone()
            if request is None:
                raise KeyError(f"Assistant request not found: {request_id}")
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM assistant_events WHERE request_id = ?",
                (request_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO assistant_events (event_id, request_id, sequence, event_type, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event.event_id, request_id, sequence, event_type, json.dumps(payload, ensure_ascii=False), _iso(now)),
            )
        return event.model_copy(update={"sequence": sequence})

    def events_after(
        self, request_id: str, *, after_sequence: int = 0, limit: int = 100
    ) -> list[AssistantEvent]:
        if after_sequence < 0 or limit < 1:
            raise ValueError("after_sequence must be nonnegative and limit must be positive")
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM assistant_events WHERE request_id = ? AND sequence > ? "
                "ORDER BY sequence ASC LIMIT ?",
                (request_id, after_sequence, limit),
            ).fetchall()
        return [
            AssistantEvent(
                event_id=row["event_id"], request_id=row["request_id"], sequence=row["sequence"],
                event_type=row["event_type"], payload=json.loads(row["payload_json"]),
                created_at=_datetime(row["created_at"]),
            )
            for row in rows
        ]

    def recover_interrupted(self) -> list[str]:
        """Recover in-flight requests left by a terminated Core process."""

        now = _now()
        timestamp = _iso(now)
        recovered: list[str] = []
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM assistant_requests "
                "WHERE state IN (?, ?, ?) ORDER BY created_at ASC",
                (
                    RequestState.GENERATING.value,
                    RequestState.STREAMING.value,
                    RequestState.EXECUTING.value,
                ),
            ).fetchall()
            for row in rows:
                request_id = row["id"]
                connection.execute(
                    "UPDATE assistant_requests SET state = ?, error_code = ?, "
                    "updated_at = ?, completed_at = ?, interrupted_at = ? WHERE id = ?",
                    (
                        RequestState.INTERRUPTED.value,
                        "core_restarted",
                        timestamp,
                        timestamp,
                        timestamp,
                        request_id,
                    ),
                )
                connection.execute(
                    "UPDATE messages SET status = ?, error_code = ?, completed_at = ? "
                    "WHERE request_id = ? AND status IN (?, ?)",
                    (
                        MessageStatus.INTERRUPTED.value,
                        "core_restarted",
                        timestamp,
                        request_id,
                        MessageStatus.PENDING.value,
                        MessageStatus.STREAMING.value,
                    ),
                )
                sequence = connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM assistant_events "
                    "WHERE request_id = ?",
                    (request_id,),
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO assistant_events "
                    "(event_id, request_id, sequence, event_type, payload_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        f"event-{uuid4().hex}",
                        request_id,
                        sequence,
                        "request.interrupted",
                        json.dumps(
                            {"reason": "core_restarted"}, ensure_ascii=False
                        ),
                        timestamp,
                    ),
                )
                recovered.append(request_id)
        return recovered


def _message_from_row(row: sqlite3.Row) -> ConversationMessage:
    return ConversationMessage(
        id=row["id"], conversation_id=row["conversation_id"], sequence=row["sequence"],
        role=MessageRole(row["role"]), content=row["content"], status=MessageStatus(row["status"]),
        client_message_id=row["client_message_id"], request_id=row["request_id"],
        provider=row["provider"], model=row["model"], error_code=row["error_code"],
        created_at=_datetime(row["created_at"]), completed_at=_datetime(row["completed_at"]),
    )


def _request_from_row(row: sqlite3.Row) -> AssistantRequest:
    return AssistantRequest(
        id=row["id"], conversation_id=row["conversation_id"], user_message_id=row["user_message_id"],
        client_message_id=row["client_message_id"], state=RequestState(row["state"]),
        parent_request_id=row["parent_request_id"], attempt=row["attempt"], error_code=row["error_code"],
        created_at=_datetime(row["created_at"]), updated_at=_datetime(row["updated_at"]),
        completed_at=_datetime(row["completed_at"]), interrupted_at=_datetime(row["interrupted_at"]),
    )
