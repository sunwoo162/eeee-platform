"""Durable, user-scoped Codex task snapshots and append-only approval audit."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from app.codex_integration.runtime import CodexTask


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CodexJournal:
    def __init__(self, sqlite_store) -> None:
        self.db = sqlite_store
        self.recover_abandoned()

    def recover_abandoned(self) -> None:
        """Never imply a pre-restart subprocess is still running or approvable."""
        with self.db._connect() as conn:
            rows = conn.execute(
                "SELECT id,snapshot_json FROM codex_agent_tasks "
                "WHERE status IN ('queued','running','approvalRequired')"
            ).fetchall()
            for row in rows:
                snapshot = json.loads(row["snapshot_json"])
                snapshot["status"] = "interrupted"
                snapshot["pendingApproval"] = None
                snapshot["error"] = "Gleave가 재시작되어 작업이 중단됐습니다."
                conn.execute(
                    "UPDATE codex_agent_tasks SET status='interrupted', "
                    "snapshot_json=?,updated_at=? WHERE id=?",
                    (json.dumps(snapshot, ensure_ascii=False), _now(), row["id"]),
                )
                sequence = conn.execute(
                    "SELECT COALESCE(MAX(sequence),0)+1 FROM codex_agent_audit WHERE task_id=?",
                    (row["id"],),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO codex_agent_audit(task_id,sequence,kind,payload_json,timestamp) "
                    "VALUES (?,?,?,?,?)",
                    (row["id"], sequence, "interrupted", json.dumps({"reason":"process_restart"}), _now()),
                )

    def save(self, task: CodexTask, event: dict | None = None) -> None:
        snapshot = task.snapshot()
        now = _now()
        with self.db._connect() as conn:
            conn.execute(
                "INSERT INTO codex_agent_tasks "
                "(id,user_id,conversation_id,project_id,status,snapshot_json,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "status=excluded.status,snapshot_json=excluded.snapshot_json,"
                "updated_at=excluded.updated_at",
                (
                    task.id, task.user_id, task.conversation_id, task.project_id,
                    task.status, json.dumps(snapshot, ensure_ascii=False), now, now,
                ),
            )
            if event is not None:
                sequence = conn.execute(
                    "SELECT COALESCE(MAX(sequence),0)+1 FROM codex_agent_audit WHERE task_id=?",
                    (task.id,),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO codex_agent_audit(task_id,sequence,kind,payload_json,timestamp) "
                    "VALUES (?,?,?,?,?)",
                    (
                        task.id, sequence, event.get("type","event"),
                        json.dumps(event,ensure_ascii=False), now,
                    ),
                )

    def append_audit(self, task: CodexTask, *, kind: str, details: dict) -> None:
        with self.db._connect() as conn:
            sequence = conn.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM codex_agent_audit WHERE task_id=?",
                (task.id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO codex_agent_audit(task_id,sequence,kind,payload_json,timestamp) "
                "VALUES (?,?,?,?,?)",
                (task.id, sequence, kind, json.dumps(details, ensure_ascii=False), _now()),
            )

    def snapshot(self, task_id: str, *, user_id: str) -> dict:
        with self.db._connect() as conn:
            row = conn.execute(
                "SELECT snapshot_json FROM codex_agent_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError("Codex task not found")
        return json.loads(row["snapshot_json"])

    def history(self, conversation_id: str, *, user_id: str) -> list[dict]:
        with self.db._connect() as conn:
            rows = conn.execute(
                "SELECT snapshot_json FROM codex_agent_tasks "
                "WHERE conversation_id=? AND user_id=? "
                "ORDER BY created_at DESC LIMIT 50",
                (conversation_id, user_id),
            ).fetchall()
        return [json.loads(row["snapshot_json"]) for row in rows]

    def audit(self, task_id: str, *, user_id: str) -> list[dict]:
        # Authorize before audit retrieval, including across a restart.
        self.snapshot(task_id, user_id=user_id)
        with self.db._connect() as conn:
            rows = conn.execute(
                "SELECT sequence,kind,payload_json,timestamp FROM codex_agent_audit "
                "WHERE task_id=? ORDER BY sequence ASC",
                (task_id,),
            ).fetchall()
        return [
            {
                "sequence": row["sequence"], "kind":row["kind"],
                "data":json.loads(row["payload_json"]), "timestamp":row["timestamp"],
            } for row in rows
        ]
