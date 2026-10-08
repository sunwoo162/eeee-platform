"""Local HTTP client for the ISEOL ChatGPT Web bridge.

The bridge owns the browser profile and the ChatGPT Web session.  EEEE only
exchanges bounded JSON over loopback; it never receives credentials or browser
cookies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.agent.protocol import AgentRequest, AgentResult


class ChatGptWebRuntime:
    """Use a logged-in ChatGPT Web session through the local ISEOL bridge."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.conversation_ref: str | None = None

    def run(self, request: AgentRequest) -> AgentResult:
        try:
            response = httpx.post(
                f"{self.base_url}/chat",
                json={
                    "text": request.prompt,
                    "conversationRef": self.conversation_ref,
                    "runId": request.run_id,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return AgentResult(
                status="unavailable",
                summary="ChatGPT Web bridge unavailable",
                events=[], changed_files=[], test_commands=[], error=str(exc),
            )

        if not isinstance(payload, dict):
            return self._failed("ChatGPT Web bridge returned an invalid response")
        conversation_ref = payload.get("conversationRef")
        if isinstance(conversation_ref, str) and conversation_ref:
            self.conversation_ref = conversation_ref
        status = payload.get("status")
        if status != "completed":
            return self._failed(str(payload.get("error") or "ChatGPT Web request was not completed"))
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            return self._failed("ChatGPT Web bridge returned no assistant message")
        return AgentResult(
            status="completed", summary=message.strip(), events=[{
                "type": "chatgpt.web.response",
                "message": message.strip(),
                "conversationRef": self.conversation_ref,
            }], changed_files=[], test_commands=[], error=None,
        )

    @staticmethod
    def _failed(message: str) -> AgentResult:
        return AgentResult(
            status="failed", summary="ChatGPT Web request failed", events=[],
            changed_files=[], test_commands=[], error=message,
        )
