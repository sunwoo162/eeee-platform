"""Offline, review-only project-memory candidate detection.

Heuristic extraction is not model inference. It NEVER writes memories by
itself; approval and dismissal are transactional human-review decisions.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from app.chat_scopes.store import WorkspaceStore

_SIGNALS = (
    "프로젝트는", "프로젝트에서", "우리 프로젝트", "우리는", "사용하기로",
    "결정했", "결정하", "기준은", "목표는", "목표로", "스택은",
    "기술 스택", "사용할 거", "사용할게", "앞으로", "기억해",
    "we decided", "we use", "the project", "our project",
    "use react", "use python", "requirement is", "the goal",
)
_SECRETS = re.compile(
    r"(?:api[_ -]?key|password|passwd|비밀번호|비밀.?키|access[_ -]?token"
    r"|bearer\s+[A-Za-z0-9]|sk-[A-Za-z0-9]|ghp_[A-Za-z0-9]|"
    r"-----BEGIN|\b\d{3}-\d{2}-\d{4}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})",
    re.IGNORECASE,
)


def memory_set_digest(notes: list[dict]) -> str:
    normalized = sorted(
        [(note["id"], note["content"]) for note in notes],
        key=lambda entry: entry[0],
    )
    return hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


class MemoryCandidates:
    def __init__(self, projects: WorkspaceStore):
        self.projects = projects
        self.db = projects.db

    def list(self, project_id: str, *, user_id: str, limit: int = 50) -> list[dict]:
        self.projects.list_memories(project_id, user_id=user_id)
        with self.db._connect() as conn:
            rows = conn.execute(
                "SELECT m.id, m.content, c.title, src.provider FROM messages m "
                "JOIN conversations c ON c.id=m.conversation_id "
                "JOIN chat_conversation_links l ON l.conversation_id=c.id "
                "JOIN chat_import_sources src ON src.conversation_id=c.id "
                "LEFT JOIN chat_memory_reviews r ON r.project_id=l.project_id "
                "AND r.source_message_id=m.id "
                "WHERE l.project_id=? AND c.user_id=? "
                "AND m.role='user' AND m.status='completed' "
                "AND r.source_message_id IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM chat_project_memories pm "
                "WHERE pm.project_id=l.project_id AND pm.source_message_id=m.id "
                "AND pm.status='active') "
                "ORDER BY m.created_at DESC,m.sequence ASC LIMIT 800",
                (project_id, user_id),
            ).fetchall()
        result = []
        for row in rows:
            raw = row["content"].strip()
            if len(raw) > 2000 or _SECRETS.search(raw):
                continue
            lowered = raw.casefold()
            matched = next((signal for signal in _SIGNALS if signal in lowered), None)
            if matched is None:
                continue
            # Preserve original phrasing: this is a proposed quote, NOT a fact.
            result.append({
                "sourceMessageId": row["id"], "sourceTitle": row["title"],
                "sourceProvider": row["provider"],
                "suggestedText": raw, "reason": f"Explicit project statement: {matched}",
                "method": "local-heuristic",
            })
            if len(result) >= min(limit, 100):
                break
        return result

    def review(
        self, project_id: str, message_id: str, *, user_id: str,
        decision: str, content: str | None = None, acknowledged_risk: bool = False,
    ) -> dict:
        if decision not in {"approve", "dismiss"}:
            raise ValueError("Review decision must be approve or dismiss")
        if decision == "approve" and (
            not content or not content.strip() or len(content.strip()) > 2000
        ):
            raise ValueError("Approved memory must contain 1-2000 characters")
        if decision == "approve" and _SECRETS.search(content or ""):
            raise ValueError("Approved memory appears to contain sensitive data")
        with self.db._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            role = self.projects._project_role(conn, project_id, user_id)
            if role == "viewer":
                raise PermissionError("Viewer cannot review memories")
            source = conn.execute(
                "SELECT m.id FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                "JOIN chat_conversation_links l ON l.conversation_id=c.id "
                "JOIN chat_import_sources src ON src.conversation_id=c.id "
                "WHERE m.id=? AND l.project_id=? AND c.user_id=? "
                "AND m.role='user' AND m.status='completed'",
                (message_id, project_id, user_id),
            ).fetchone()
            if source is None:
                raise KeyError("Imported user message not found in this project")
            reviewed = conn.execute(
                "SELECT 1 FROM chat_memory_reviews WHERE project_id=? AND source_message_id=?",
                (project_id, message_id),
            ).fetchone()
            approved = conn.execute(
                "SELECT 1 FROM chat_project_memories WHERE project_id=? "
                "AND source_message_id=? AND status='active'",
                (project_id, message_id),
            ).fetchone()
            if reviewed or approved:
                raise ValueError("This source has already been reviewed")
            if decision == "approve":
                # Exact duplicates remain disallowed even when a model says new.
                normalized = re.sub(r"\s+", "", content or "").casefold()
                existing_texts = conn.execute(
                    "SELECT content FROM chat_project_memories "
                    "WHERE project_id=? AND status='active'",
                    (project_id,),
                ).fetchall()
                if any(
                    re.sub(r"\s+", "", row["content"]).casefold() == normalized
                    for row in existing_texts
                ):
                    raise ValueError("Identical approved memory already exists")
                analysis = conn.execute(
                    "SELECT verdict,analysis_json FROM chat_memory_analyses "
                    "WHERE project_id=? AND source_message_id=? AND analyzed_by=?",
                    (project_id, message_id, user_id),
                ).fetchone()
                if analysis is not None:
                    report = json.loads(analysis["analysis_json"])
                    approved_notes = conn.execute(
                        "SELECT id,content FROM chat_project_memories "
                        "WHERE project_id=? AND status='active'",
                        (project_id,),
                    ).fetchall()
                    if report.get("memorySetDigest") != memory_set_digest(approved_notes):
                        raise ValueError("Approved memories changed. Re-run analysis before approval")
                    if (
                        analysis["verdict"] in {"conflict", "duplicate"}
                        and not acknowledged_risk
                    ):
                        raise ValueError("Confirm the flagged conflict or duplicate before approval")
            now = datetime.now(UTC).isoformat()
            memory_id = None
            if decision == "approve":
                memory_id = f"project-memory-{uuid4().hex}"
                conn.execute(
                    "INSERT INTO chat_project_memories "
                    "(id,project_id,content,created_by_user_id,source_message_id,status,created_at) "
                    "VALUES (?,?,?,?,?,'active',?)",
                    (memory_id, project_id, content.strip(), user_id, message_id, now),
                )
                conn.execute(
                    "INSERT INTO chat_memory_revisions "
                    "(id,project_id,memory_id,version,action,actor_user_id,"
                    "old_content,new_content,source_message_id,occurred_at) "
                    "VALUES (?,?,?,1,'created',?,NULL,?,?,?)",
                    (f"memory-revision-{uuid4().hex}",project_id,memory_id,
                     user_id,content.strip(),message_id,now),
                )
            conn.execute(
                "INSERT INTO chat_memory_reviews "
                "(project_id,source_message_id,reviewed_by,decision,reviewed_at,memory_id) "
                "VALUES (?,?,?,?,?,?)",
                (
                    project_id, message_id, user_id,
                    "approved" if decision == "approve" else "dismissed",
                    now, memory_id,
                ),
            )
        return {
            "projectId": project_id, "sourceMessageId": message_id,
            "decision": decision, "memoryId": memory_id,
        }
