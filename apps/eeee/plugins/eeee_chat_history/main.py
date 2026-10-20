"""Standalone entrypoint for the optional EEEE chat history window."""

from __future__ import annotations

import argparse
import json
from typing import Any
from uuid import uuid4

import httpx

try:
    from .window import ChatHistoryWindow
except ImportError:  # Direct execution from the installed plugin directory.
    from window import ChatHistoryWindow


class CoreApiClient:
    """Small client kept inside the plugin so the plugin has no core import dependency."""

    def __init__(self, base_url: str, *, timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = httpx.request(method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise RuntimeError(str(detail))
        return response.json() if response.status_code != 204 else {}

    def get_conversations(self, *, query: str = "", limit: int = 50) -> list[dict[str, object]]:
        """Read the same durable conversation store used by the main desktop UI."""
        result = self._request(
            "GET", "/v1/conversations", params={"limit": limit}
        )
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise RuntimeError("Core returned an invalid conversation list")
        normalized: list[dict[str, object]] = []
        needle = query.strip().casefold()
        for item in result["items"]:
            if not isinstance(item, dict):
                continue
            conversation_id = str(item.get("id") or "")
            title = str(item.get("title") or "새 대화")
            if not conversation_id or (needle and needle not in title.casefold()):
                continue
            normalized.append({
                "conversationId": conversation_id,
                "preview": title,
                "messageCount": int(item.get("messageCount") or 0),
                "updatedAt": item.get("updatedAt"),
            })
        return normalized

    def get_conversation(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        before_id: int | None = None,
    ) -> dict[str, object]:
        if not conversation_id or "/" in conversation_id or "\\" in conversation_id:
            raise ValueError("conversation_id must be a path-safe value")
        result = self._request(
            "GET",
            f"/v1/conversations/{conversation_id}/messages",
            params={"afterSequence": 0, "limit": limit},
        )
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise RuntimeError("Core returned an invalid conversation")
        turns = [
            {
                "id": item.get("id"),
                "role": item.get("role"),
                "content": item.get("content"),
                "status": item.get("status"),
                "createdAt": item.get("createdAt"),
            }
            for item in result["items"]
            if isinstance(item, dict)
        ]
        return {"conversationId": conversation_id, "turns": turns, "nextBeforeId": None}

    def send_conversation_message(
        self, text: str, *, conversation_id: str = "desktop-default"
    ) -> dict[str, object]:
        conversation_id = conversation_id.strip()
        if not conversation_id:
            conversations = self.get_conversations(limit=1)
            if conversations:
                conversation_id = str(conversations[0]["conversationId"])
            else:
                created = self._request(
                    "POST", "/v1/conversations", json={"title": "새 대화"}
                )
                if not isinstance(created, dict) or not created.get("id"):
                    raise RuntimeError("Core could not create a conversation")
                conversation_id = str(created["id"])
        request = self._request(
            "POST",
            f"/v1/conversations/{conversation_id}/turns",
            json={
                "clientMessageId": f"eeee-chat-history-{uuid4().hex}",
                "content": text,
            },
        )
        if not isinstance(request, dict) or not isinstance(request.get("requestId"), str):
            raise RuntimeError("Core returned an invalid conversation request")
        events = self._request_events(str(request["requestId"]))
        for event in events:
            if event.get("eventType") == "message.completed":
                payload = event.get("payload")
                if isinstance(payload, dict):
                    return {
                        "status": "completed",
                        "message": str(payload.get("content") or ""),
                        "requestId": request["requestId"],
                        "conversationId": conversation_id,
                    }
            if event.get("eventType") in {"request.failed", "request.interrupted", "request.cancelled"}:
                payload = event.get("payload")
                reason = payload.get("error") if isinstance(payload, dict) else None
                return {
                    "status": "failed",
                    "message": str(reason or "대화 요청이 완료되지 않았어."),
                    "requestId": request["requestId"],
                    "conversationId": conversation_id,
                }
        return {
            "status": "accepted",
            "message": "답변을 기다리는 중이야.",
            "requestId": request["requestId"],
            "conversationId": conversation_id,
        }

    def _request_events(self, request_id: str) -> list[dict[str, object]]:
        with httpx.stream(
            "GET",
            f"{self.base_url}/v1/requests/{request_id}/events",
            params={"afterSequence": 0, "timeoutSeconds": min(self.timeout, 60.0)},
            timeout=self.timeout + 5.0,
        ) as response:
            if response.is_error:
                raise RuntimeError(response.text)
            events: list[dict[str, object]] = []
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
            return events
        result = self._request(
            "POST",
            "/api/assistant/route",
            json={"text": text, "conversationId": conversation_id},
        )
        if not isinstance(result, dict):
            raise RuntimeError("Core returned an invalid assistant response")
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EEEE chat history plugin")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--conversation-id", default="")
    args = parser.parse_args(argv)

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    window = ChatHistoryWindow(CoreApiClient(args.api_url), conversation_id=args.conversation_id)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
