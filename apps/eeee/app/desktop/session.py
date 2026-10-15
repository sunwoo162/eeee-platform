"""Headless Desktop control-plane state and commands."""

from __future__ import annotations

from typing import Any
from uuid import uuid4


class DesktopSession:
    """Keep the Desktop presentation model separate from the Qt window."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.project_id: str | None = None
        self.assistant_job_id: str | None = None
        self.snapshot: dict[str, object] = {}

    def refresh(self, project_id: str | None = None) -> dict[str, object]:
        if project_id is not None:
            self.project_id = project_id
        self.snapshot = self.client.get_desktop_state(self.project_id)
        if self.assistant_job_id and hasattr(self.client, "get_assistant_job"):
            job = self.client.get_assistant_job(self.assistant_job_id)
            result = job.get("result") if isinstance(job, dict) else None
            status = job.get("status") if isinstance(job, dict) else None
            if status == "completed" and isinstance(result, dict):
                project_id = result.get("project_id") or result.get("projectId")
                if isinstance(project_id, str) and project_id:
                    self.project_id = project_id
                    self.snapshot = self.client.get_desktop_state(project_id)
                result_status = result.get("status")
                blocked = result_status in {"blocked", "failed", "awaiting_configuration"}
                self.snapshot.update({
                    "state": "blocked" if blocked else "completed",
                    "message": result.get(
                        "message",
                        "EEEE 작업이 완료됐지만 추가 설정이 필요해."
                        if blocked else "EEEE 작업이 완료됐어.",
                    ),
                    "assistantJobId": self.assistant_job_id,
                })
                self.assistant_job_id = None
            elif status == "failed":
                self.snapshot.update({
                    "state": "blocked",
                    "message": f"EEEE 작업이 중단됐어: {job.get('error') or '알 수 없는 오류'}",
                    "assistantJobId": self.assistant_job_id,
                })
            elif status == "scheduled":
                self.snapshot.update({
                    "state": "scheduled",
                    "message": "EEEE가 작업을 예약해뒀어.",
                    "assistantJobId": self.assistant_job_id,
                })
            elif status in {"queued", "running", "paused"}:
                message = {
                    "queued": "EEEE가 작업을 시작할 준비 중이야.",
                    "running": "EEEE가 백그라운드에서 작업 진행 중이야.",
                    "paused": "EEEE 작업이 잠시 멈춰 있어.",
                }[status]
                self.snapshot.update({
                    "state": "working" if status != "paused" else "blocked",
                    "message": message,
                    "assistantJobId": self.assistant_job_id,
                })
        return self.snapshot

    def route(self, text: str, workspace: str | None = None) -> dict[str, object]:
        result = self.client.route_assistant(text, workspace)
        job_id = result.get("jobId")
        if isinstance(job_id, str) and job_id:
            self.assistant_job_id = job_id
        selected_project = result.get("project_id")
        if isinstance(selected_project, str) and selected_project:
            self.project_id = selected_project
        snapshot = self.refresh()
        snapshot["assistantRoute"] = result
        if not isinstance(job_id, str) or not job_id:
            # A direct EEEE/plugin response has no project snapshot to carry
            # its state. Even project-scoped synchronous responses must remain
            # visible instead of being overwritten by the project snapshot.
            route_status = result.get("status")
            state = {
                "completed": "completed",
                "accepted": "working",
                "blocked": "blocked",
                "awaiting_configuration": "blocked",
                "plugin_required": "blocked",
                "needs_clarification": "idle",
            }.get(route_status, "idle")
            snapshot.update({
                "state": state,
                "message": result.get("message", "EEEE가 응답을 준비했어."),
                "assistantJobId": result.get("jobId"),
            })
        self.snapshot = snapshot
        return snapshot

    def issue_pairing_code(self) -> dict[str, object]:
        result = self.client.issue_pairing_code()
        return _without_secrets(result)


def _without_secrets(value: dict[str, object]) -> dict[str, object]:
    return {
        key: item
        for key, item in value.items()
        if key.replace("_", "").lower() not in {"accesstoken", "token", "password"}
    }


class ConversationSession:
    """Desktop-only conversation state backed exclusively by the Core API."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.conversation_id: str | None = None
        self.request_id: str | None = None
        self.messages: list[dict[str, object]] = []
        self.state = "idle"
        self.draft = ""

    def begin_input(self) -> None:
        self.state = "input"
        self.draft = ""

    def open(self, conversation_id: str) -> list[dict[str, object]]:
        payload = self.client.get_conversation_messages(conversation_id)
        items = payload.get("items", [])
        self.conversation_id = conversation_id
        self.messages = [
            item for item in items if isinstance(item, dict)
        ] if isinstance(items, list) else []
        self.state = "idle"
        return self.messages

    def reconnect(self) -> list[dict[str, object]]:
        if self.conversation_id is None:
            return self.messages
        return self.open(self.conversation_id)

    def submit(self, text: str) -> dict[str, object]:
        value = text.strip()
        if not value:
            raise ValueError("conversation text must not be empty")
        self.draft = value
        self.state = "submitting"
        try:
            if self.conversation_id is None:
                conversation = self.client.create_conversation()
                self.conversation_id = str(conversation["id"])
            request = self.client.submit_turn(
                self.conversation_id,
                value,
                f"desktop-{uuid4().hex}",
            )
        except Exception:
            self.state = "error"
            raise
        self.messages.append({"role": "user", "content": value, "status": "completed"})
        self.request_id = str(request["requestId"])
        self.state = "streaming"
        return request

    def apply_events(
        self, request: dict[str, object], events: list[dict[str, object]]
    ) -> None:
        request_id = request.get("requestId")
        if isinstance(request_id, str):
            self.request_id = request_id
        assistant: dict[str, object] | None = None
        for message in reversed(self.messages):
            if message.get("role") == "assistant" and message.get("status") == "streaming":
                assistant = message
                break
        for event in events:
            event_type = event.get("eventType")
            payload = event.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            if event_type == "message.started":
                assistant = {"role": "assistant", "content": "", "status": "streaming"}
                self.messages.append(assistant)
            elif event_type == "message.delta":
                if assistant is None:
                    assistant = {"role": "assistant", "content": "", "status": "streaming"}
                    self.messages.append(assistant)
                assistant["content"] = str(assistant.get("content", "")) + str(
                    payload.get("delta", "")
                )
            elif event_type == "message.completed":
                if assistant is None:
                    assistant = {"role": "assistant", "content": "", "status": "streaming"}
                    self.messages.append(assistant)
                assistant["content"] = str(payload.get("content", assistant.get("content", "")))
                assistant["status"] = "completed"
                self.state = "answer"
            elif event_type in {"request.failed", "request.cancelled", "request.interrupted"}:
                self.state = "error"
        if self.state == "streaming" and assistant is not None and assistant.get("status") == "completed":
            self.state = "answer"
