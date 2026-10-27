"""Codex app-server JSONL bridge with explicit, per-request approvals.

No shell=True, browser automation, default unrestricted sandbox, or implicit
permission grants. Each job is one bounded local process; the frontend polls
status so chat remains responsive.
"""
from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


class CodexUnavailable(RuntimeError):
    pass


class CodexProtocolError(RuntimeError):
    pass


@dataclass
class CodexTask:
    id: str
    user_id: str
    project_id: str
    conversation_id: str
    directory: str
    prompt: str
    mode: str
    status: str = "queued"
    thread_id: str | None = None
    turn_id: str | None = None
    answer: str = ""
    diff: str = ""
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    pending_approval: dict[str, Any] | None = None
    _approval_ready: threading.Event = field(default_factory=threading.Event, repr=False)
    _approval_decision: str | None = field(default=None, repr=False)
    _cancelled: threading.Event = field(default_factory=threading.Event, repr=False)
    _process: subprocess.Popen[str] | None = field(default=None, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def publish(self, event: str, value: str) -> None:
        with self._lock:
            self.events.append({
                "index": (self.events[-1]["index"] if self.events else 0) + 1,
                "type": event,
                "text": value[:3000],
            })
            self.events = self.events[-150:]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "id": self.id, "projectId": self.project_id,
                "conversationId": self.conversation_id,
                "directory": self.directory, "mode": self.mode,
                "status": self.status, "answer": self.answer[-20000:],
                "diff": self.diff[-20000:], "error": self.error,
                "events": self.events.copy(),
                "pendingApproval": (
                    self.pending_approval.copy()
                    if self.pending_approval is not None else None
                ),
            }


class CodexTaskManager:
    """Bounded in-process task manager; no task runs until an explicit POST."""

    def __init__(self, executable: str | None = None, timeout_seconds: float = 600):
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self._tasks: dict[str, CodexTask] = {}
        self._lock = threading.RLock()

    def configured_executable(self) -> str:
        # npm on Windows creates codex.cmd; subprocess with shell=False must
        # receive the executable path, not a user-controlled command string.
        command = self.executable or (
            shutil.which("codex.exe") or shutil.which("codex.cmd") or shutil.which("codex")
        )
        if not command:
            raise CodexUnavailable("Codex CLI가 설치되어 있지 않습니다.")
        return command

    def start(
        self, *, user_id: str, project_id: str, conversation_id: str,
        directory: Path, prompt: str, mode: str = "readOnly",
        confirmed_write: bool = False,
    ) -> CodexTask:
        if mode not in {"readOnly", "workspaceWrite"}:
            raise ValueError("invalid Codex mode")
        if mode == "workspaceWrite" and not confirmed_write:
            raise PermissionError("쓰기 작업 시작 전 명시적 동의가 필요합니다.")
        prompt = prompt.strip()
        if not prompt or len(prompt) > 15_000:
            raise ValueError("task prompt must be 1 to 15000 characters")
        command = self.configured_executable()
        with self._lock:
            active = sum(
                t.status in {"queued", "running", "approvalRequired"}
                for t in self._tasks.values()
                if t.user_id == user_id
            )
            if active >= 2:
                raise ValueError("동시 Codex 작업은 사용자당 2개까지 가능합니다.")
            if len(self._tasks) > 120:
                self._tasks = {
                    key: value for key, value in self._tasks.items()
                    if value.status in {"queued", "running", "approvalRequired"}
                }
            task = CodexTask(
                id=f"codex-task-{uuid4().hex}", user_id=user_id,
                project_id=project_id, conversation_id=conversation_id,
                directory=str(directory), prompt=prompt, mode=mode,
            )
            self._tasks[task.id] = task
        threading.Thread(
            target=self._execute, args=(task, command), daemon=True,
            name=f"gleave-codex-{task.id}",
        ).start()
        return task

    def get(self, task_id: str, *, user_id: str) -> CodexTask:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None or task.user_id != user_id:
            raise KeyError("Codex task not found")
        return task

    def approve(self, task_id: str, approval_id: str, decision: str, *, user_id: str) -> None:
        if decision not in {"accept", "decline"}:
            raise ValueError("Unsupported approval decision")
        task = self.get(task_id, user_id=user_id)
        with task._lock:
            approval = task.pending_approval
            if task.status != "approvalRequired" or approval is None:
                raise ValueError("No pending approval")
            if approval["id"] != approval_id:
                raise ValueError("Approval ID does not match pending request")
            task._approval_decision = decision
            task._approval_ready.set()

    def cancel(self, task_id: str, *, user_id: str) -> None:
        task = self.get(task_id, user_id=user_id)
        task._cancelled.set()
        task._approval_ready.set()
        with task._lock:
            if task.status not in {"completed", "failed", "cancelled"}:
                task.status = "cancelled"
            proc = task._process
        if proc is not None and proc.poll() is None:
            proc.kill()

    def shutdown(self) -> None:
        """Do not leave Codex subprocesses running after the Gleave Core exits."""
        with self._lock:
            tasks = list(self._tasks.values())
        for task in tasks:
            if task.status in {"queued", "running", "approvalRequired"}:
                self.cancel(task.id, user_id=task.user_id)

    def _execute(self, task: CodexTask, command: str) -> None:
        proc: subprocess.Popen[str] | None = None
        try:
            if task._cancelled.is_set():
                return
            proc = subprocess.Popen(
                [command, "app-server", "--stdio"],
                cwd=task.directory,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", bufsize=1, shell=False,
            )
            with task._lock:
                task._process = proc
                if task._cancelled.is_set():
                    proc.kill()
                    return
                task.status = "running"
            self._run_protocol(task, proc)
        except _TurnComplete:
            pass
        except (OSError, CodexProtocolError, CodexUnavailable, ValueError) as exc:
            task.error = str(exc)[:500]
            if not task._cancelled.is_set():
                task.status = "failed"
            task.publish("error", task.error)
        except Exception:  # noqa: BLE001
            # Do not leak stack traces, environment, or API keys to the client.
            task.error = "Codex 실행에 실패했습니다. 작업 로그를 확인해 주세요."
            if not task._cancelled.is_set():
                task.status = "failed"
        finally:
            if proc is not None:
                if proc.poll() is None:
                    proc.kill()
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    pass
            with task._lock:
                task._process = None

    def _run_protocol(self, task: CodexTask, proc: subprocess.Popen[str]) -> None:
        if proc.stdin is None or proc.stdout is None:
            raise CodexProtocolError("Codex stdio 연결 실패")
        received: queue.Queue[dict | None] = queue.Queue()

        def pump() -> None:
            for line in proc.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    received.put(message)
            received.put(None)

        threading.Thread(target=pump, daemon=True, name="gleave-codex-read").start()
        deadline = time.monotonic() + self.timeout_seconds

        def send(message: dict) -> None:
            if proc.poll() is not None:
                raise CodexProtocolError("Codex 프로세스가 종료됐습니다.")
            try:
                proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
                proc.stdin.flush()
            except OSError as exc:
                raise CodexProtocolError("Codex 프로토콜 전송 실패") from exc

        def receive() -> dict:
            while not task._cancelled.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CodexProtocolError("Codex 작업 제한 시간을 초과했습니다.")
                try:
                    packet = received.get(timeout=min(remaining, 0.2))
                except queue.Empty:
                    continue
                if packet is None:
                    raise CodexProtocolError("Codex 연결이 종료됐습니다.")
                if isinstance(packet.get("method"), str):
                    self._notification(task, packet, send)
                    continue
                return packet
            raise CodexProtocolError("Codex 작업을 취소했습니다.")

        def rpc(index: int, method: str, params: dict) -> dict:
            send({"id": index, "method": method, "params": params})
            while True:
                reply = receive()
                if reply.get("id") != index:
                    continue
                if "error" in reply:
                    raise CodexProtocolError(f"Codex {method} 요청이 거절되었습니다.")
                return reply.get("result") or {}

        rpc(1, "initialize", {
            "clientInfo": {
                "name": "gleave", "title": "Gleave", "version": "0.1.0",
            },
        })
        send({"method": "initialized", "params": {}})
        thread = rpc(2, "thread/start", {
            "cwd": task.directory,
            "approvalPolicy": "onRequest",
            "sandbox": "readOnly" if task.mode == "readOnly" else "workspaceWrite",
            "serviceName": "gleave",
        })
        task.thread_id = thread.get("thread", {}).get("id")
        if not task.thread_id:
            raise CodexProtocolError("Codex thread ID를 받지 못했습니다.")
        started = rpc(3, "turn/start", {
            "threadId": task.thread_id,
            "cwd": task.directory,
            "approvalPolicy": "onRequest",
            "sandboxPolicy": (
                {"type": "readOnly"}
                if task.mode == "readOnly"
                else {"type": "workspaceWrite", "writableRoots": [task.directory],
                      "networkAccess": False}
            ),
            "input": [{"type": "text", "text": task.prompt}],
        })
        task.turn_id = started.get("turn", {}).get("id")
        if not task.turn_id:
            raise CodexProtocolError("Codex turn ID를 받지 못했습니다.")
        while True:
            reply = receive()
            # Turn completion is surfaced in _notification(), not rpc response.
            if reply.get("id") is not None:
                continue

    def _notification(self, task: CodexTask, packet: dict, send) -> None:
        method = packet["method"]
        params = packet.get("params") or {}
        if "id" in packet:
            if method in {
                "item/commandExecution/requestApproval",
                "item/fileChange/requestApproval",
            }:
                request_id = packet["id"]
                approval_id = str(uuid4())
                with task._lock:
                    task.pending_approval = {
                        "id": approval_id, "method": method,
                        "reason": str(params.get("reason") or "")[:350],
                        "command": str(params.get("command") or "")[:1000],
                    }
                    task._approval_decision = None
                    task._approval_ready.clear()
                    task.status = "approvalRequired"
                task.publish("approval", f"사용자 승인 필요: {method}")
                if not task._approval_ready.wait(timeout=120) or task._cancelled.is_set():
                    decision = "decline"
                else:
                    decision = task._approval_decision or "decline"
                send({"id": request_id, "result": {"decision": decision}})
                with task._lock:
                    task.pending_approval = None
                    if not task._cancelled.is_set():
                        task.status = "running"
            else:
                # All unsupported server requests fail closed, never guessed.
                send({"id": packet["id"], "error": {"code": -32601, "message": "Gleave does not grant this permission"}})
            return
        if method == "item/agentMessage/delta":
            delta = params.get("delta")
            if isinstance(delta, str):
                task.answer = (task.answer + delta)[-50000:]
                task.publish("answer", delta)
        elif method == "turn/diff/updated":
            diff = params.get("diff")
            if isinstance(diff, str):
                task.diff = diff[-50000:]
                task.publish("diff", "변경사항 미리보기가 업데이트됐습니다.")
        elif method == "item/completed":
            item = params.get("item") or {}
            if item.get("type") == "commandExecution":
                task.publish("command", str(item.get("command") or "")[:1000])
            elif item.get("type") == "fileChange":
                task.publish("fileChange", str(len(item.get("changes", []))) + " file changes")
            elif item.get("type") == "agentMessage" and not task.answer:
                task.answer = str(item.get("text") or "")[-50000:]
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            status = turn.get("status")
            task.status = "completed" if status == "completed" else (
                "cancelled" if status == "interrupted" else "failed"
            )
            if task.status == "failed":
                task.error = str((turn.get("error") or {}).get("message") or "Codex 작업이 실패했습니다.")[:500]
            task.publish("completed", task.status)
            # _run_protocol's receive() needs a terminal marker.
            raise _TurnComplete()
        elif method == "error":
            task.publish("warning", str((params.get("error") or {}).get("message") or "Codex warning")[:500])


class _TurnComplete(Exception):
    """Internal control flow: the turn/completed notification ends the stream."""
