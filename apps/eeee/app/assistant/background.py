"""Durable background execution for the EEEE Desktop Assistant."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from threading import Lock
from typing import Any
from uuid import uuid4

from app.storage.sqlite import SQLiteStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobTransitionError(RuntimeError):
    """A durable assistant job cannot make the requested state transition."""


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
        self._operations: dict[str, Callable[[], dict[str, Any]]] = {}
        self._lock = Lock()
        self._owner_token = f"supervisor-{uuid4().hex}"
        self._lease_seconds = 300

    def submit(
        self, request_id: str, operation: Callable[[], dict[str, Any]],
        *, input_data: dict[str, Any] | None = None,
    ) -> str:
        job_id = f"assistant-job-{uuid4().hex}"
        stored_job_id = self._create(job_id, request_id, input_data or {})
        if stored_job_id != job_id:
            # Another request won the durable request-id race.  Reuse its
            # job instead of starting a second project operation.
            return stored_job_id
        with self._lock:
            self._operations[job_id] = operation
        future = self._pool.submit(self._run, job_id, operation)
        with self._lock:
            self._futures[job_id] = future
        return job_id

    def get(self, job_id: str, *, user_id: str | None = None) -> dict[str, object]:
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT job_id, request_id, status, input_json, result_json, error, created_at, updated_at, "
                "lease_owner, lease_expires_at "
                "FROM assistant_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Assistant job not found: {job_id}")
        job = {
            "jobId": row["job_id"],
            "requestId": row["request_id"],
            "status": row["status"],
            "input": json.loads(row["input_json"]),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "leaseOwner": row["lease_owner"],
            "leaseExpiresAt": row["lease_expires_at"],
        }
        if user_id is not None and self._job_user_id(job) != user_id:
            raise KeyError(f"Assistant job not found: {job_id}")
        return job

    def find_by_request_id(
        self, request_id: str, *, user_id: str | None = None,
    ) -> dict[str, object] | None:
        """Return the durable job for a request, if one already exists."""

        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT job_id, input_json FROM assistant_jobs WHERE request_id = ? "
                "ORDER BY created_at DESC",
                (request_id,),
            ).fetchall()
        for row in rows:
            job = self.get(str(row["job_id"]))
            if user_id is None or self._job_user_id(job) == user_id:
                return job
        return None

    def list_jobs(
        self, *, status: str | None = None, limit: int = 100,
        user_id: str | None = None,
    ) -> list[dict[str, object]]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        with self.store._connect() as connection:
            if status is None and user_id is None:
                rows = connection.execute(
                    "SELECT job_id FROM assistant_jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            elif status is None:
                rows = connection.execute(
                    "SELECT job_id FROM assistant_jobs ORDER BY created_at DESC",
                ).fetchall()
            else:
                query = "SELECT job_id FROM assistant_jobs WHERE status = ? ORDER BY created_at DESC"
                parameters: tuple[object, ...] = (status,)
                if user_id is None:
                    query += " LIMIT ?"
                    parameters += (limit,)
                rows = connection.execute(query, parameters).fetchall()
        jobs = [self.get(str(row["job_id"])) for row in rows]
        if user_id is not None:
            jobs = [job for job in jobs if self._job_user_id(job) == user_id]
        return jobs[:limit]

    def pause(self, job_id: str, *, user_id: str | None = None) -> dict[str, object]:
        self.get(job_id, user_id=user_id)
        return self._transition(job_id, "paused", {"queued", "running", "paused"}, user_id=user_id)

    def cancel(self, job_id: str, *, user_id: str | None = None) -> dict[str, object]:
        self.get(job_id, user_id=user_id)
        return self._transition(
            job_id, "cancelled", {"queued", "running", "paused", "cancelled"}, user_id=user_id
        )

    def resume(
        self,
        job_id: str,
        operation_factory: Callable[[dict[str, object]], Callable[[], dict[str, Any]]] | None = None,
        *,
        user_id: str | None = None,
    ) -> dict[str, object]:
        self.get(job_id, user_id=user_id)
        return self._restart(
            job_id,
            expected={"paused"},
            operation_factory=operation_factory,
            user_id=user_id,
        )

    def retry(
        self,
        job_id: str,
        operation_factory: Callable[[dict[str, object]], Callable[[], dict[str, Any]]] | None = None,
        *,
        user_id: str | None = None,
    ) -> dict[str, object]:
        self.get(job_id, user_id=user_id)
        return self._restart(
            job_id,
            expected={"failed", "cancelled"},
            operation_factory=operation_factory,
            user_id=user_id,
        )

    def shutdown(self, *, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=False)

    def resume_pending(self, operation_factory: Callable[[dict[str, object]], Callable[[], dict[str, Any]]]) -> list[str]:
        now = _now()
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT job_id, request_id, input_json, status FROM assistant_jobs "
                "WHERE status = 'queued' OR (status = 'running' AND "
                "(lease_expires_at IS NULL OR lease_expires_at < ?)) ORDER BY created_at",
                (now,),
            ).fetchall()
        resumed: list[str] = []
        for row in rows:
            input_data = json.loads(row["input_json"])
            lease_expires_at = self._lease_expiry()
            with self.store._connect() as connection:
                if row["status"] == "queued":
                    cursor = connection.execute(
                        "UPDATE assistant_jobs SET status = 'running', lease_owner = ?, "
                        "lease_expires_at = ?, error = NULL, updated_at = ? "
                        "WHERE job_id = ? AND status = 'queued'",
                        (self._owner_token, lease_expires_at, now, row["job_id"]),
                    )
                else:
                    cursor = connection.execute(
                        "UPDATE assistant_jobs SET status = 'running', lease_owner = ?, "
                        "lease_expires_at = ?, error = NULL, updated_at = ? "
                        "WHERE job_id = ? AND status = 'running' AND "
                        "(lease_expires_at IS NULL OR lease_expires_at < ?)",
                        (self._owner_token, lease_expires_at, now, row["job_id"], now),
                    )
            if cursor.rowcount != 1:
                continue
            operation = operation_factory({
                "jobId": row["job_id"], "requestId": row["request_id"], "input": input_data,
            })
            with self._lock:
                self._operations[row["job_id"]] = operation
            future = self._pool.submit(self._run, row["job_id"], operation, True)
            with self._lock:
                self._futures[row["job_id"]] = future
            resumed.append(row["job_id"])
        return resumed

    def _lease_expiry(self) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=self._lease_seconds)).isoformat()

    def _create(self, job_id: str, request_id: str, input_data: dict[str, Any]) -> str:
        timestamp = _now()
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT job_id FROM assistant_jobs WHERE request_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (request_id,),
            ).fetchone()
            if existing is not None:
                return str(existing["job_id"])
            connection.execute(
                "INSERT INTO assistant_jobs "
                "(job_id, request_id, status, input_json, result_json, error, created_at, updated_at) "
                "VALUES (?, ?, 'queued', ?, NULL, NULL, ?, ?)",
                (job_id, request_id, json.dumps(input_data, ensure_ascii=False), timestamp, timestamp),
            )
        return job_id

    def _run(
        self, job_id: str, operation: Callable[[], dict[str, Any]], claimed: bool = False,
    ) -> None:
        # Claim the queued job atomically. A separate read followed by an
        # unconditional write lets pause/cancel be overwritten by this worker.
        if not claimed and not self._claim_queued(job_id):
            return
        try:
            result = operation()
        except Exception as exc:
            self._update_if_current(
                job_id,
                "failed",
                expected={"running"},
                error=str(exc).strip() or type(exc).__name__,
                owner=self._owner_token,
            )
            return
        self._update_if_current(job_id, "completed", expected={"running"}, result=result, owner=self._owner_token)

    def _claim_queued(self, job_id: str) -> bool:
        timestamp = _now()
        with self.store._connect() as connection:
            cursor = connection.execute(
                "UPDATE assistant_jobs SET status = 'running', lease_owner = ?, "
                "lease_expires_at = ?, updated_at = ? "
                "WHERE job_id = ? AND status = 'queued'",
                (self._owner_token, self._lease_expiry(), timestamp, job_id),
            )
        return cursor.rowcount == 1

    def _transition(
        self, job_id: str, target: str, allowed: set[str], *, user_id: str | None = None,
    ) -> dict[str, object]:
        allowed_placeholders = ", ".join("?" for _ in allowed)
        with self.store._connect() as connection:
            cursor = connection.execute(
                "UPDATE assistant_jobs SET status = ?, updated_at = ?, "
                "lease_owner = NULL, lease_expires_at = NULL "
                "WHERE job_id = ? AND status IN (" + allowed_placeholders + ")",
                (target, _now(), job_id, *sorted(allowed)),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT status FROM assistant_jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"Assistant job not found: {job_id}")
                current = str(row["status"])
                if current not in allowed:
                    raise JobTransitionError(
                        f"Assistant job {job_id} cannot transition from {current} to {target}"
                    )
                raise JobTransitionError(
                    f"Assistant job {job_id} changed before it could transition to {target}"
                )
        return self.get(job_id, user_id=user_id)

    def _restart(
        self,
        job_id: str,
        *,
        expected: set[str],
        operation_factory: Callable[[dict[str, object]], Callable[[], dict[str, Any]]] | None,
        user_id: str | None,
    ) -> dict[str, object]:
        job = self.get(job_id, user_id=user_id)
        status = str(job["status"])
        if status not in expected:
            raise JobTransitionError(
                f"Assistant job {job_id} cannot restart from {status}"
            )
        with self._lock:
            operation = self._operations.get(job_id)
        if operation is None and operation_factory is not None:
            operation = operation_factory(job)
        if operation is None:
            raise JobTransitionError(f"Assistant job {job_id} has no resumable operation")
        expected_placeholders = ", ".join("?" for _ in expected)
        with self.store._connect() as connection:
            cursor = connection.execute(
                "UPDATE assistant_jobs SET status = 'queued', result_json = NULL, "
                "error = NULL, lease_owner = NULL, lease_expires_at = NULL, updated_at = ? "
                "WHERE job_id = ? AND status IN ("
                + expected_placeholders + ")",
                (_now(), job_id, *sorted(expected)),
            )
            if cursor.rowcount != 1:
                raise JobTransitionError(
                    f"Assistant job {job_id} changed before it could restart"
                )
        with self._lock:
            self._operations[job_id] = operation
        future = self._pool.submit(self._run, job_id, operation)
        with self._lock:
            self._futures[job_id] = future
        return self.get(job_id, user_id=user_id)

    @staticmethod
    def _job_user_id(job: dict[str, object]) -> str:
        input_data = job.get("input")
        if isinstance(input_data, dict):
            value = input_data.get("userId")
            if isinstance(value, str) and value.strip():
                return value
        return "local-user"

    def _update_if_current(
        self,
        job_id: str,
        status: str,
        *,
        expected: set[str],
        result: dict[str, Any] | None = None,
        error: str | None = None,
        owner: str | None = None,
    ) -> bool:
        expected_placeholders = ", ".join("?" for _ in expected)
        with self.store._connect() as connection:
            where = "WHERE job_id = ? AND status IN (" + expected_placeholders + ")"
            parameters: tuple[object, ...] = (
                status,
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                error,
                _now(),
                job_id,
                *sorted(expected),
            )
            if owner is not None:
                where += " AND lease_owner = ?"
                parameters += (owner,)
            cursor = connection.execute(
                "UPDATE assistant_jobs SET status = ?, result_json = ?, error = ?, updated_at = ?, "
                "lease_owner = NULL, lease_expires_at = NULL " + where,
                parameters,
            )
        return cursor.rowcount == 1

