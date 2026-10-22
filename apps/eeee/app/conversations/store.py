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


def _normalise_user_id(value: str) -> str:
    user_id = value.strip()
    if not user_id:
        raise ValueError("user_id is required")
    return user_id


def _conversation_from_row(row: sqlite3.Row) -> Conversation:
    return Conversation(
        id=row["id"],
        user_id=row["user_id"] if "user_id" in row.keys() else "local-user",
        title=row["title"],
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
        archived_at=_datetime(row["archived_at"]),
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ConversationStore:
    def __init__(self, store) -> None:
        self.store = store

    def ensure_conversation(
        self, conversation_id: str, *, title: str = "새 대화", user_id: str = "local-user"
    ) -> Conversation:
        """Return a stable conversation, creating it for legacy route callers.

        The assistant route historically accepted a caller-provided conversation
        id without first creating a ``/v1`` conversation.  Keeping that id in
        the canonical store lets the desktop route and the chat-history API
        observe the same transcript.
        """

        conversation_id = conversation_id.strip()
        user_id = _normalise_user_id(user_id)
        if not conversation_id:
            raise ValueError("conversation_id is required")
        now = _now()
        with self.store._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO conversations "
                "(id, user_id, title, created_at, updated_at, archived_at) VALUES (?, ?, ?, ?, ?, NULL)",
                (conversation_id, user_id, title.strip() or "새 대화", _iso(now), _iso(now)),
            )
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Conversation not found: {conversation_id}")
        return _conversation_from_row(row)

    def create_conversation(
        self, title: str = "새 대화", *, user_id: str = "local-user"
    ) -> Conversation:
        user_id = _normalise_user_id(user_id)
        now = _now()
        conversation = Conversation(
            id=f"conversation-{uuid4().hex}",
            user_id=user_id,
            title=title.strip() or "새 대화",
            created_at=now,
            updated_at=now,
        )
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO conversations (id, user_id, title, created_at, updated_at, archived_at) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                (conversation.id, conversation.user_id, conversation.title, _iso(now), _iso(now)),
            )
        return conversation

    def get_conversation(
        self, conversation_id: str, *, user_id: str = "local-user"
    ) -> Conversation:
        user_id = _normalise_user_id(user_id)
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Conversation not found: {conversation_id}")
        return _conversation_from_row(row)

    def record_route_turn(
        self,
        conversation_id: str,
        *,
        user_id: str = "local-user",
        user_content: str,
        assistant_content: str,
        request_id: str,
        assistant_status: MessageStatus = MessageStatus.COMPLETED,
        provider: str | None = None,
        model: str | None = None,
        error_code: str | None = None,
    ) -> tuple[ConversationMessage, ConversationMessage]:
        """Write one assistant-route turn to the canonical transcript.

        A route may first persist an accepted/background response and later
        replace only the assistant message with the verified result.  The
        request id is therefore the idempotency key for both messages.
        """

        conversation_id = conversation_id.strip()
        user_id = _normalise_user_id(user_id)
        request_id = request_id.strip()
        user_content = user_content.strip()
        assistant_content = assistant_content.strip()
        if not conversation_id or not request_id:
            raise ValueError("conversation_id and request_id are required")
        if not user_content or not assistant_content:
            raise ValueError("route turn content must not be empty")
        now = _now()
        terminal = {
            MessageStatus.COMPLETED,
            MessageStatus.FAILED,
            MessageStatus.CANCELLED,
            MessageStatus.INTERRUPTED,
        }
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            conversation = connection.execute(
                "SELECT id, user_id FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if conversation is None:
                connection.execute(
                    "INSERT INTO conversations "
                    "(id, user_id, title, created_at, updated_at, archived_at) VALUES (?, ?, ?, ?, ?, NULL)",
                    (conversation_id, user_id, "새 대화", _iso(now), _iso(now)),
                )
            elif conversation["user_id"] != user_id:
                raise KeyError(f"Conversation not found: {conversation_id}")

            def find(role: MessageRole) -> sqlite3.Row | None:
                return connection.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? "
                    "AND request_id = ? AND role = ? ORDER BY sequence ASC LIMIT 1",
                    (conversation_id, request_id, role.value),
                ).fetchone()

            def insert(role: MessageRole, content: str, status: MessageStatus) -> sqlite3.Row:
                sequence = connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
                message_id = f"message-{uuid4().hex}"
                completed_at = _iso(now) if status in terminal else None
                client_message_id = (
                    f"route:{request_id}:user" if role is MessageRole.USER else None
                )
                connection.execute(
                    "INSERT INTO messages (id, conversation_id, sequence, role, content, status, "
                    "client_message_id, request_id, provider, model, error_code, created_at, completed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        message_id, conversation_id, sequence, role.value, content, status.value,
                        client_message_id, request_id, provider, model, error_code,
                        _iso(now), completed_at,
                    ),
                )
                return connection.execute(
                    "SELECT * FROM messages WHERE id = ?", (message_id,)
                ).fetchone()

            user_row = find(MessageRole.USER)
            if user_row is None:
                user_row = insert(MessageRole.USER, user_content, MessageStatus.COMPLETED)
            elif user_row["content"] != user_content:
                raise ValueError("request_id was reused with different user content")

            assistant_row = find(MessageRole.ASSISTANT)
            if assistant_row is None:
                assistant_row = insert(MessageRole.ASSISTANT, assistant_content, assistant_status)
            else:
                connection.execute(
                    "UPDATE messages SET content = ?, status = ?, provider = ?, model = ?, "
                    "error_code = ?, completed_at = ? WHERE id = ?",
                    (
                        assistant_content, assistant_status.value, provider, model, error_code,
                        _iso(now) if assistant_status in terminal else None, assistant_row["id"],
                    ),
                )
                assistant_row = connection.execute(
                    "SELECT * FROM messages WHERE id = ?", (assistant_row["id"],)
                ).fetchone()
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (_iso(now), conversation_id),
            )
        return _message_from_row(user_row), _message_from_row(assistant_row)

    def find_pending_route(
        self, conversation_id: str, user_content: str, *, user_id: str = "local-user"
    ) -> str | None:
        """Find an unfinished route for the same conversation and user text.

        Legacy route callers do not always send a client request id.  During
        that window, a network retry or a double click must attach to the
        existing background request instead of creating a second project.
        Completed turns are intentionally excluded so asking the same thing
        later remains a valid new request.
        """

        user_id = _normalise_user_id(user_id)
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT user_message.request_id FROM messages AS user_message "
                "JOIN messages AS assistant_message ON assistant_message.conversation_id = user_message.conversation_id "
                "AND assistant_message.request_id = user_message.request_id "
                "JOIN conversations AS conversation ON conversation.id = user_message.conversation_id "
                "WHERE user_message.conversation_id = ? AND conversation.user_id = ? "
                "AND user_message.role = 'user' AND user_message.content = ? "
                "AND assistant_message.role = 'assistant' "
                "AND assistant_message.status IN (?, ?) "
                "ORDER BY user_message.sequence DESC LIMIT 1",
                (
                    conversation_id,
                    user_id,
                    user_content.strip(),
                    MessageStatus.PENDING.value,
                    MessageStatus.STREAMING.value,
                ),
            ).fetchone()
        return str(row["request_id"]) if row is not None and row["request_id"] else None

    def record_route_lifecycle(
        self,
        conversation_id: str,
        route_request_id: str,
        status: str,
        *,
        user_id: str = "local-user",
        error_code: str | None = None,
    ) -> AssistantRequest | None:
        """Project the legacy assistant route into the canonical request ledger.

        The route already owns a stable request id for idempotency. Reusing it
        here keeps `/api` and `/v1` observability aligned without creating a
        second request identity or a second user message.
        """

        conversation_id = conversation_id.strip()
        route_request_id = route_request_id.strip()
        user_id = _normalise_user_id(user_id)
        if not conversation_id or not route_request_id:
            raise ValueError("conversation_id and route_request_id are required")
        target = {
            "accepted": RequestState.EXECUTING,
            "pending": RequestState.EXECUTING,
            "completed": RequestState.COMPLETED,
            "blocked": RequestState.FAILED,
            "failed": RequestState.FAILED,
            "unsupported": RequestState.FAILED,
            "needs_clarification": RequestState.FAILED,
            "plugin_required": RequestState.FAILED,
            "awaiting_configuration": RequestState.FAILED,
        }.get(status, RequestState.FAILED)
        now = _now()
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            user = connection.execute(
                "SELECT messages.id FROM messages "
                "JOIN conversations ON conversations.id = messages.conversation_id "
                "WHERE messages.conversation_id = ? AND conversations.user_id = ? "
                "AND request_id = ? AND role = 'user' ORDER BY sequence LIMIT 1",
                (conversation_id, user_id, route_request_id),
            ).fetchone()
            if user is None:
                return None
            row = connection.execute(
                "SELECT * FROM assistant_requests WHERE id = ?", (route_request_id,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO assistant_requests "
                    "(id, conversation_id, user_message_id, client_message_id, state, "
                    "parent_request_id, attempt, error_code, created_at, updated_at, completed_at, interrupted_at) "
                    "VALUES (?, ?, ?, ?, ?, NULL, 1, ?, ?, ?, ?, NULL)",
                    (
                        route_request_id, conversation_id, user["id"],
                        f"route:{route_request_id}", RequestState.RECEIVED.value,
                        None, _iso(now), _iso(now), None,
                    ),
                )
                self._append_event_in_connection(
                    connection, route_request_id, "request.accepted",
                    {"requestId": route_request_id, "source": "assistant.route"}, now,
                )
                connection.execute(
                    "UPDATE assistant_requests SET state = ?, updated_at = ? WHERE id = ?",
                    (RequestState.PERSISTED_USER_MESSAGE.value, _iso(now), route_request_id),
                )
                self._append_event_in_connection(
                    connection, route_request_id, "request.classified",
                    {"status": RequestState.PERSISTED_USER_MESSAGE.value}, now,
                )
                connection.execute(
                    "UPDATE assistant_requests SET state = ?, updated_at = ? WHERE id = ?",
                    (RequestState.EXECUTING.value, _iso(now), route_request_id),
                )
                self._append_event_in_connection(
                    connection, route_request_id, "request.executing",
                    {"status": RequestState.EXECUTING.value}, now,
                )
            else:
                current = RequestState(row["state"])
                if current in {
                    RequestState.COMPLETED, RequestState.FAILED,
                    RequestState.CANCELLED, RequestState.INTERRUPTED,
                }:
                    if target == RequestState.EXECUTING and status in {"accepted", "pending"}:
                        attempt = int(row["attempt"] or 1) + 1
                        connection.execute(
                            "UPDATE assistant_requests SET state = ?, attempt = ?, "
                            "error_code = NULL, updated_at = ?, completed_at = NULL, "
                            "interrupted_at = NULL WHERE id = ?",
                            (
                                RequestState.EXECUTING.value,
                                attempt,
                                _iso(now),
                                route_request_id,
                            ),
                        )
                        self._append_event_in_connection(
                            connection,
                            route_request_id,
                            "request.retry",
                            {"requestId": route_request_id, "attempt": attempt},
                            now,
                        )
                        self._append_event_in_connection(
                            connection,
                            route_request_id,
                            "request.executing",
                            {"status": RequestState.EXECUTING.value, "attempt": attempt},
                            now,
                        )
                    else:
                        result = connection.execute(
                            "SELECT * FROM assistant_requests WHERE id = ?", (route_request_id,)
                        ).fetchone()
                        return _request_from_row(result)
            if target != RequestState.EXECUTING:
                completed_at = _iso(now)
                final_error = error_code if target == RequestState.FAILED else None
                connection.execute(
                    "UPDATE assistant_requests SET state = ?, error_code = ?, updated_at = ?, "
                    "completed_at = ? WHERE id = ?",
                    (target.value, final_error, _iso(now), completed_at, route_request_id),
                )
                event_type = "request.completed" if target == RequestState.COMPLETED else "request.failed"
                self._append_event_in_connection(
                    connection, route_request_id, event_type,
                    {"status": target.value, "errorCode": final_error}, now,
                )
            result = connection.execute(
                "SELECT * FROM assistant_requests WHERE id = ?", (route_request_id,)
            ).fetchone()
        return _request_from_row(result)

    @staticmethod
    def _append_event_in_connection(
        connection: sqlite3.Connection,
        request_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: datetime,
    ) -> None:
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM assistant_events WHERE request_id = ?",
            (request_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO assistant_events "
            "(event_id, request_id, sequence, event_type, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"event-{uuid4().hex}", request_id, sequence, event_type,
                json.dumps(payload, ensure_ascii=False), _iso(created_at),
            ),
        )

    def list_transcript_summaries(
        self,
        *,
        query: str = "",
        limit: int = 50,
        before_updated_at: str | None = None,
        before_conversation_id: str | None = None,
        user_id: str = "local-user",
    ) -> list[dict[str, object]]:
        """List canonical transcript summaries in the legacy history shape."""

        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if (before_updated_at is None) != (before_conversation_id is None):
            raise ValueError(
                "before_updated_at and before_conversation_id must be provided together"
            )
        if before_updated_at is not None and not before_updated_at.strip():
            raise ValueError("before_updated_at is required when paging")
        if before_conversation_id is not None and not before_conversation_id.strip():
            raise ValueError("before_conversation_id is required when paging")
        if before_updated_at is not None:
            try:
                datetime.fromisoformat(before_updated_at)
            except ValueError as exc:
                raise ValueError("before_updated_at must be an ISO-8601 timestamp") from exc
        query = query.strip()
        user_id = _normalise_user_id(user_id)
        pattern = f"%{_escape_like(query)}%"
        filters = [
            "c.user_id = ?",
            "c.archived_at IS NULL",
            "(? = '' OR c.id LIKE ? ESCAPE '\\' OR m.content LIKE ? ESCAPE '\\')",
        ]
        parameters: list[object] = [user_id, query, pattern, pattern]
        if before_updated_at is not None and before_conversation_id is not None:
            filters.append(
                "(c.updated_at < ? OR (c.updated_at = ? AND c.id < ?))"
            )
            parameters.extend(
                [before_updated_at, before_updated_at, before_conversation_id]
            )
        parameters.append(limit)
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT c.id, COUNT(m.id) AS message_count, "
                "MAX(m.sequence) AS latest_sequence, MAX(c.updated_at) AS updated_at "
                "FROM conversations c JOIN messages m ON m.conversation_id = c.id "
                f"WHERE {' AND '.join(filters)} "
                "GROUP BY c.id ORDER BY updated_at DESC, c.id DESC LIMIT ?",
                parameters,
            ).fetchall()
            summaries: list[dict[str, object]] = []
            for row in rows:
                latest = connection.execute(
                    "SELECT content FROM messages WHERE conversation_id = ? "
                    "ORDER BY sequence DESC LIMIT 1", (row["id"],)
                ).fetchone()
                if latest is None:
                    continue
                summaries.append({
                    "conversationId": str(row["id"]),
                    "messageCount": int(row["message_count"]),
                    "preview": str(latest["content"]),
                    "updatedAt": str(row["updated_at"]),
                })
            return summaries

    def get_transcript(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        before_sequence: int | None = None,
        user_id: str = "local-user",
    ) -> dict[str, object]:
        """Return a bounded canonical transcript page for the history client."""

        conversation_id = conversation_id.strip()
        if not conversation_id:
            raise ValueError("conversation_id is required")
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        if before_sequence is not None and before_sequence < 1:
            raise ValueError("before_sequence must be positive")
        self.get_conversation(conversation_id, user_id=user_id)
        with self.store._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            if before_sequence is None:
                rows = connection.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? "
                    "ORDER BY sequence DESC LIMIT ?", (conversation_id, limit + 1)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? AND sequence < ? "
                    "ORDER BY sequence DESC LIMIT ?",
                    (conversation_id, before_sequence, limit + 1),
                ).fetchall()
        has_older = len(rows) > limit
        page = list(reversed(rows[:limit]))
        turns = [
            {
                "id": int(row["sequence"]),
                "messageId": str(row["id"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                "status": str(row["status"]),
                "requestId": row["request_id"],
                "provider": row["provider"],
                "model": row["model"],
                "errorCode": row["error_code"],
                "createdAt": str(row["created_at"]),
            }
            for row in page
        ]
        return {
            "conversationId": conversation_id,
            "messageCount": int(count),
            "turns": turns,
            "nextBeforeId": turns[0]["id"] if has_older and turns else None,
        }

    def list_conversations(
        self, *, limit: int = 50, user_id: str = "local-user"
    ) -> list[Conversation]:
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        user_id = _normalise_user_id(user_id)
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM conversations WHERE user_id = ? AND archived_at IS NULL "
                "ORDER BY updated_at DESC, id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [
            Conversation(
                id=row["id"],
                user_id=row["user_id"] if "user_id" in row.keys() else "local-user",
                title=row["title"],
                created_at=_datetime(row["created_at"]),
                updated_at=_datetime(row["updated_at"]),
                archived_at=_datetime(row["archived_at"]),
            )
            for row in rows
        ]

    def message_count(self, conversation_id: str) -> int:
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS message_count FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return int(row["message_count"] if row is not None else 0)

    def get_messages(
        self, conversation_id: str, *, after_sequence: int = 0, limit: int = 100,
        user_id: str = "local-user",
    ) -> list[ConversationMessage]:
        if after_sequence < 0 or limit < 1:
            raise ValueError("after_sequence must be nonnegative and limit must be positive")
        user_id = _normalise_user_id(user_id)
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT messages.* FROM messages "
                "JOIN conversations ON conversations.id = messages.conversation_id "
                "WHERE messages.conversation_id = ? AND conversations.user_id = ? "
                "AND messages.sequence > ? ORDER BY messages.sequence ASC LIMIT ?",
                (conversation_id, user_id, after_sequence, limit),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def recent_conversation_turns(
        self, conversation_id: str, *, limit: int = 12, user_id: str = "local-user"
    ) -> list[dict[str, str]]:
        """Return bounded canonical transcript context in provider format."""

        if limit <= 0:
            return []
        user_id = _normalise_user_id(user_id)
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT messages.role, messages.content FROM messages "
                "JOIN conversations ON conversations.id = messages.conversation_id "
                "WHERE messages.conversation_id = ? AND conversations.user_id = ? "
                "ORDER BY messages.sequence DESC LIMIT ?",
                (conversation_id, user_id, limit),
            ).fetchall()
        return [
            {"role": str(row["role"]), "content": str(row["content"])}
            for row in reversed(rows)
        ]

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
            # Serialize the read/sequence/insert critical section so two
            # retries with the same client id cannot allocate the same turn.
            connection.execute("BEGIN IMMEDIATE")
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
        provider: str | None = None,
        model: str | None = None,
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
                "UPDATE messages SET content = ?, status = ?, provider = ?, model = ?, error_code = ?, completed_at = ? "
                "WHERE id = ?",
                (
                    content, status.value, provider, model, error_code,
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
        request, _created = self.create_request_with_status(
            conversation_id,
            user_message_id,
            client_message_id,
            parent_request_id=parent_request_id,
            attempt=attempt,
        )
        return request

    def create_request_with_status(
        self, conversation_id: str, user_message_id: str, client_message_id: str,
        *, parent_request_id: str | None = None, attempt: int = 1,
    ) -> tuple[AssistantRequest, bool]:
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
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM assistant_requests WHERE conversation_id = ? "
                "AND client_message_id = ?",
                (conversation_id, client_message_id),
            ).fetchone()
            if existing is not None:
                if existing["user_message_id"] != user_message_id:
                    raise ValueError(
                        "client_message_id was reused with a different user message"
                    )
                return _request_from_row(existing), False
            connection.execute(
                "INSERT INTO assistant_requests (id, conversation_id, user_message_id, "
                "client_message_id, state, parent_request_id, attempt, error_code, created_at, "
                "updated_at, completed_at, interrupted_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL)",
                (
                    request.id, conversation_id, user_message_id, client_message_id,
                    request.state.value, parent_request_id, attempt, _iso(now), _iso(now),
                ),
            )
        return request, True

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

    def get_request_for_user(
        self, request_id: str, *, user_id: str = "local-user"
    ) -> AssistantRequest:
        user_id = _normalise_user_id(user_id)
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT assistant_requests.* FROM assistant_requests "
                "JOIN conversations ON conversations.id = assistant_requests.conversation_id "
                "WHERE assistant_requests.id = ? AND conversations.user_id = ?",
                (request_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Assistant request not found: {request_id}")
        return _request_from_row(row)

    def get_conversation_for_request(self, request_id: str) -> Conversation:
        """Resolve the owning conversation for internal request execution."""

        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT conversations.* FROM conversations "
                "JOIN assistant_requests ON assistant_requests.conversation_id = conversations.id "
                "WHERE assistant_requests.id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Assistant request not found: {request_id}")
        return _conversation_from_row(row)

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
