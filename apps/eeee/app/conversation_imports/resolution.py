"""Atomic, explicitly approved replacement of a conflicting project memory.

A model cannot run this action. Only the owner's direct request with the
exact analyzed source, referenced target, current project-memory digest,
target version and conflict acknowledgement is accepted.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from app.conversation_imports.candidates import (
    _SECRETS,
    MemoryCandidates,
    memory_set_digest,
)


class MemoryConflictResolver:
    def __init__(self, candidates: MemoryCandidates):
        self.candidates = candidates
        self.db = candidates.db

    def replace(
        self, project_id: str, source_message_id: str, *,
        user_id: str, memory_id: str, content: str,
        expected_version: int, acknowledged_risk: bool,
    ) -> dict:
        if not acknowledged_risk:
            raise PermissionError("Explicit conflict acknowledgement is required")
        content = content.strip()
        if not content or len(content) > 2000 or _SECRETS.search(content):
            raise ValueError("Replacement must be safe and between 1 and 2000 characters")
        if expected_version < 1:
            raise ValueError("Invalid expected memory version")
        with self.db._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            role = self.candidates.projects._project_role(conn, project_id, user_id)
            if role == "viewer":
                raise PermissionError("Viewer cannot replace project memory")
            source = conn.execute(
                "SELECT m.id FROM messages m "
                "JOIN conversations c ON c.id=m.conversation_id "
                "JOIN chat_conversation_links link ON link.conversation_id=c.id "
                "JOIN chat_import_sources src ON src.conversation_id=c.id "
                "WHERE link.project_id=? AND m.id=? AND c.user_id=? "
                "AND m.role='user' AND m.status='completed'",
                (project_id, source_message_id, user_id),
            ).fetchone()
            if source is None:
                raise KeyError("Source is not an imported message owned by this user")
            reviewed = conn.execute(
                "SELECT 1 FROM chat_memory_reviews WHERE project_id=? AND source_message_id=?",
                (project_id, source_message_id),
            ).fetchone()
            if reviewed:
                raise ValueError("Candidate has already been reviewed")
            analysis = conn.execute(
                "SELECT verdict,analysis_json FROM chat_memory_analyses "
                "WHERE project_id=? AND source_message_id=? AND analyzed_by=?",
                (project_id, source_message_id, user_id),
            ).fetchone()
            if analysis is None or analysis["verdict"] != "conflict":
                raise ValueError("An explicit conflict analysis is required before replacement")
            report = json.loads(analysis["analysis_json"])
            if memory_id not in report.get("relatedMemoryIds", []):
                raise ValueError("The target memory was not referenced in this analysis")
            approved = conn.execute(
                "SELECT id,content FROM chat_project_memories "
                "WHERE project_id=? AND status='active'",
                (project_id,),
            ).fetchall()
            if memory_set_digest(approved) != report.get("memorySetDigest"):
                raise ValueError("Approved memories changed. Analyze this conflict again")
            target = conn.execute(
                "SELECT content,source_message_id FROM chat_project_memories "
                "WHERE id=? AND project_id=? AND status='active'",
                (memory_id,project_id),
            ).fetchone()
            if target is None:
                raise KeyError("Active target memory not found")
            current_version = conn.execute(
                "SELECT COALESCE(MAX(version),0) FROM chat_memory_revisions "
                "WHERE memory_id=? AND project_id=?",
                (memory_id,project_id),
            ).fetchone()[0]
            if current_version != expected_version:
                raise ValueError("Memory version changed. Reload before replacing")
            normalized = re.sub(r"\s+", "", content).casefold()
            if any(
                row["id"] != memory_id
                and re.sub(r"\s+", "", row["content"]).casefold() == normalized
                for row in approved
            ):
                raise ValueError("Identical approved memory already exists elsewhere")
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "UPDATE chat_project_memories SET content=?,source_message_id=? "
                "WHERE id=? AND project_id=? AND status='active'",
                (content,source_message_id,memory_id,project_id),
            )
            conn.execute(
                "INSERT INTO chat_memory_revisions "
                "(id,project_id,memory_id,version,action,actor_user_id,"
                "old_content,new_content,source_message_id,occurred_at) "
                "VALUES (?,?,?,?,'updated',?,?,?,?,?)",
                (
                    f"memory-revision-{uuid4().hex}", project_id,memory_id,
                    current_version+1,user_id,target["content"],content,
                    source_message_id,now,
                ),
            )
            conn.execute(
                "INSERT INTO chat_memory_reviews "
                "(project_id,source_message_id,reviewed_by,decision,reviewed_at,memory_id) "
                "VALUES (?,? ,?,'approved',?,?)",
                (project_id,source_message_id,user_id,now,memory_id),
            )
        return {
            "projectId":project_id,"sourceMessageId":source_message_id,
            "memoryId":memory_id,"version":current_version+1,
            "content":content,"action":"replaced",
        }
