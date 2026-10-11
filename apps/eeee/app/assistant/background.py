"""Durable background execution for the EEEE Desktop Assistant."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
import json
from threading import Lock
from typing import Any
from uuid import uuid4

from app.storage.sqlite import SQLiteStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BackgroundExecutionSupervisor:
    """Run accepted assistant work outside the request thread.

    The database row is written before a worker is scheduled. The row is the
    user-visible truth; a future disappearing cannot turn a failed job into a
    successful one.
    """

    def __init__(self, store: SQLiteStore, *, max_workers: int = 1) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self.store = store
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="eeee-job")
        self._futures: dict[str, Future[None]] = {}
        self._lock = Lock()

    def submit(
        self, request_id: str, operation: Callable[[], dict[str, Any]],
        *, input_data: dict[str, Any] | None = None,
    ) -> str:
        job_id = f"assistant-job-{uuid4().hex}"
        self._create(job_id, request_id, input_data or {})
        future = self._pool.submit(self._run, job_id, operation)
        with self._lock:
            self._futures[job_id] = future
        return job_id

    def get(self, job_id: str) -> dict[str, object]:
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT job_id, request_id, status, input_json, result_json, error, created_at, updated_at "
                "FROM assistant_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Assistant job not found: {job_id}")
        return {
            "jobId": row["job_id"],
            "requestId": row["request_id"],
            "status": row["status"],
            "input": json.loads(row["input_json"]),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def shutdown(self, *, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=False)

    def resume_pending(self, operation_factory: Callable[[dict[str, object]], Callable[[], dict[str, Any]]]) -> list[str]:
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT job_id, request_id, input_json FROM assistant_jobs "
                "WHERE status IN ('queued', 'running', 'paused') ORDER BY created_at"
            ).fetchall()
        resumed: list[str] = []
        for row in rows:
            input_data = json.loads(row["input_json"])
            with self.store._connect() as connection:
                connection.execute(
                    "UPDATE assistant_jobs SET status = 'queued', error = NULL, updated_at = ? WHERE job_id = ?",
                    (_now(), row["job_id"]),
                )
            future = self._pool.submit(self._run, row["job_id"], operation_factory({
                "jobId": row["job_id"], "requestId": row["request_id"], "input": input_data,
            }))
            with self._lock:
                self._futures[row["job_id"]] = future
            resumed.append(row["job_id"])
        return resumed

    def _create(self, job_id: str, request_id: str, input_data: dict[str, Any]) -> None:
        timestamp = _now()
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO assistant_jobs "
                "(job_id, request_id, status, input_json, result_json, error, created_at, updated_at) "
                "VALUES (?, ?, 'queued', ?, NULL, NULL, ?, ?)",
                (job_id, request_id, json.dumps(input_data, ensure_ascii=False), timestamp, timestamp),
            )

    def _run(self, job_id: str, operation: Callable[[], dict[str, Any]]) -> None:
        self._update(job_id, "running")
        try:
            result = operation()
        except Exception as exc:
            self._update(job_id, "failed", error=str(exc).strip() or type(exc).__name__)
            return
        self._update(job_id, "completed", result=result)

    def _update(
        self, job_id: str, status: str, *, result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.store._connect() as connection:
            connection.execute(
                "UPDATE assistant_jobs SET status = ?, result_json = ?, error = ?, updated_at = ? "
                "WHERE job_id = ?",
                (status, json.dumps(result, ensure_ascii=False) if result is not None else None,
                 error, _now(), job_id),
            )

