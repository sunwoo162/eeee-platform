"""Atomic, deduplicated transcript import into owner-scoped canonical chats."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.chat_scopes.store import WorkspaceStore
from app.conversation_imports.parser import ImportedChat
from app.conversations.store import ConversationStore


class ConversationImportService:
    def __init__(self, conversations: ConversationStore, projects: WorkspaceStore):
        self.conversations = conversations
        self.projects = projects
        self.db = conversations.store

    def import_selected(
        self, chats: list[ImportedChat], selected: list[int], *, user_id: str,
        project_id: str | None = None,
    ) -> dict:
        if not selected or len(selected) > 20 or len(set(selected)) != len(selected):
            raise ValueError("한 번에 1~20개 대화를 선택해야 합니다.")
        if any(not isinstance(index, int) or isinstance(index, bool)
               or index < 0 or index >= len(chats) for index in selected):
            raise ValueError("올바르지 않은 대화 선택입니다.")
        if project_id is not None:
            self.projects.require_project_editor(project_id, user_id=user_id)
        imported, skipped = [], []
        for index in selected:
            item = chats[index]
            if not item.messages:
                skipped.append({"index": index, "reason": "empty"})
                continue
            result = self._import_one(item, user_id=user_id, project_id=project_id)
            if result is None:
                skipped.append({"index": index, "reason": "duplicate"})
            else:
                imported.append(result)
        return {"imported": imported, "skipped": skipped}

    def _import_one(
        self, item: ImportedChat, *, user_id: str, project_id: str | None,
    ) -> dict | None:
        now = datetime.now(UTC).isoformat()
        conversation_id = f"conversation-{uuid4().hex}"
        with self.db._connect() as conn:
            # Prevent concurrent imports of the same source from creating
            # duplicate canonical messages or orphan conversations.
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT conversation_id FROM chat_import_sources "
                "WHERE user_id=? AND provider=? AND source_id=?",
                (user_id, item.provider, item.source_id),
            ).fetchone()
            if existing:
                return None
            if project_id is not None:
                editor = conn.execute(
                    "SELECT m.role FROM chat_projects p "
                    "JOIN chat_workspace_members m ON m.workspace_id=p.workspace_id "
                    "WHERE p.id=? AND m.user_id=?",
                    (project_id, user_id),
                ).fetchone()
                if editor is None or editor["role"] not in {"owner", "editor"}:
                    raise PermissionError("프로젝트에 기록을 추가할 권한이 없습니다.")
            conn.execute(
                "INSERT INTO conversations "
                "(id,user_id,title,created_at,updated_at,archived_at) "
                "VALUES (?,?,?,?,?,NULL)",
                (conversation_id, user_id, item.title[:120], now, now),
            )
            for sequence, (role, text) in enumerate(item.messages, 1):
                conn.execute(
                    "INSERT INTO messages "
                    "(id,conversation_id,sequence,role,content,status,"
                    "client_message_id,request_id,provider,model,error_code,"
                    "created_at,completed_at) VALUES (?,?,?,?,?,'completed',"
                    "NULL,NULL,?,NULL,NULL,?,?)",
                    (
                        f"message-{uuid4().hex}", conversation_id, sequence,
                        role, text, f"import:{item.provider}", now, now,
                    ),
                )
            conn.execute(
                "INSERT INTO chat_import_sources "
                "(conversation_id,user_id,provider,source_id,source_digest,imported_at) "
                "VALUES (?,?,?,?,?,?)",
                (conversation_id,user_id,item.provider,item.source_id,item.digest,now),
            )
            if project_id is not None:
                conn.execute(
                    "INSERT INTO chat_conversation_links "
                    "(conversation_id,project_id,linked_by_user_id,linked_at) "
                    "VALUES (?,?,?,?)",
                    (conversation_id, project_id, user_id, now),
                )
        return {
            "conversationId":conversation_id, "provider":item.provider,
            "title":item.title, "projectId":project_id,
            "messageCount":len(item.messages),
        }

    def origin(self, conversation_id: str, *, user_id: str) -> dict | None:
        self.conversations.get_conversation(conversation_id, user_id=user_id)
        with self.db._connect() as conn:
            row = conn.execute(
                "SELECT provider,source_id,source_digest,imported_at FROM "
                "chat_import_sources WHERE conversation_id=? AND user_id=?",
                (conversation_id,user_id),
            ).fetchone()
        return dict(row) if row is not None else None
