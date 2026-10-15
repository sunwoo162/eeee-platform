"""Local HTTP client for the ISEOL ChatGPT Web bridge.

The bridge owns the browser profile and the ChatGPT Web session.  EEEE only
exchanges bounded JSON over loopback; it never receives credentials or browser
cookies.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
import time
from typing import Any
from dataclasses import dataclass

import httpx

from app.agent.protocol import AgentRequest, AgentResult
from app.assistant.profile import load_profile


@dataclass(frozen=True)
class ChatGptWebStatus:
    status: str
    error_code: str | None = None
    message: str | None = None


class ChatGptWebRuntime:
    """Use a logged-in ChatGPT Web session through the local ISEOL bridge."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 120.0,
        fresh_conversation: bool = False,
        mode: str = "assistant",
        profile_path: Path | None = None,
        conversation_state_path: Path | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.fresh_conversation = fresh_conversation
        self.mode = mode
        self.profile_path = profile_path
        self.conversation_state_path = conversation_state_path
        self._turn_lock = Lock()
        self.conversation_ref: str | None = (
            None if fresh_conversation else self._load_conversation_ref()
        )

    def status(self) -> ChatGptWebStatus:
        """Check the bridge health without opening a browser or sending a prompt."""

        try:
            response = httpx.get(f"{self.base_url}/health", timeout=0.5)
            if response.status_code >= 400:
                return ChatGptWebStatus(
                    status="unavailable",
                    error_code="chatgpt_web_unavailable",
                    message=f"ChatGPT Web bridge returned HTTP {response.status_code}",
                )
            payload = response.json()
            ready = (
                isinstance(payload, dict)
                and payload.get("service") == "chatgpt-web-bridge"
                and payload.get("connected") is True
                and payload.get("browserStatus") == "ready"
            )
            if ready:
                return ChatGptWebStatus(status="ready")
            return ChatGptWebStatus(
                status="unavailable",
                error_code="chatgpt_web_not_ready",
                message="ChatGPT Web bridge is not connected",
            )
        except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError) as exc:
            return ChatGptWebStatus(
                status="unavailable",
                error_code="chatgpt_web_unavailable",
                message=str(exc) or "ChatGPT Web bridge is unavailable",
            )

    def run(self, request: AgentRequest) -> AgentResult:
        # The bridge conversation reference is mutable shared state.  A
        # concurrent general turn could otherwise send two prompts with the
        # same reference and assign whichever response arrives last.
        with self._turn_lock:
            return self._run_locked(request)

    def _run_locked(self, request: AgentRequest) -> AgentResult:
        new_conversation = self.fresh_conversation
        body = {
            "text": request.prompt,
            "conversationRef": self.conversation_ref,
            "newConversation": new_conversation,
            "mode": self.mode,
            "runId": request.run_id,
            "profile": load_profile(self.profile_path),
        }
        payload: object | None = None
        for attempt in range(2):
            try:
                response = httpx.post(
                    f"{self.base_url}/chat",
                    json=body,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                break
            except httpx.HTTPStatusError as exc:
                transient = exc.response.status_code in {502, 503, 504}
                if transient and attempt == 0:
                    time.sleep(0.15)
                    continue
                detail = ""
                try:
                    error_payload = exc.response.json()
                    if isinstance(error_payload, dict):
                        detail = str(error_payload.get("error") or error_payload.get("message") or "")
                except (ValueError, TypeError):
                    detail = ""
                if exc.response.status_code == 401 or any(
                    marker in detail.lower()
                    for marker in ("auth", "login", "sign-in", "locator-missing", "composer")
                ):
                    self.conversation_ref = None
                    self._clear_conversation_ref()
                    detail = "ChatGPT 로그인이 필요해. 브라우저에서 로그인하면 EEEE가 이어서 응답할 수 있어."
                return AgentResult(
                    status="unavailable",
                    summary="ChatGPT Web bridge unavailable",
                    events=[], changed_files=[], test_commands=[],
                    error=f"{exc}{(': ' + detail) if detail else ''}",
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                if attempt == 0:
                    time.sleep(0.15)
                    continue
                return AgentResult(
                    status="unavailable",
                    summary="ChatGPT Web bridge unavailable",
                    events=[], changed_files=[], test_commands=[], error=str(exc),
                )
            except (httpx.HTTPError, ValueError) as exc:
                return AgentResult(
                    status="unavailable",
                    summary="ChatGPT Web bridge unavailable",
                    events=[], changed_files=[], test_commands=[], error=str(exc),
                )

        if payload is None:
            return self._failed("ChatGPT Web bridge returned no response")

        if not isinstance(payload, dict):
            return self._failed("ChatGPT Web bridge returned an invalid response")
        status = payload.get("status")
        if status != "completed":
            return self._failed(str(payload.get("error") or "ChatGPT Web request was not completed"))
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            return self._failed("ChatGPT Web bridge returned no assistant message")
        conversation_ref = payload.get("conversationRef")
        if isinstance(conversation_ref, str) and conversation_ref:
            self.conversation_ref = conversation_ref
            self._persist_conversation_ref(conversation_ref)
        # A specialist may need several structured turns. Only its first turn
        # should create an isolated conversation; continuations stay in that
        # conversation so the bridge can attribute pending responses safely.
        self.fresh_conversation = False
        return AgentResult(
            status="completed", summary=message.strip(), events=[{
                "type": "chatgpt.web.response",
                "message": message.strip(),
                "conversationRef": self.conversation_ref,
            }], changed_files=[], test_commands=[], error=None,
        )

    def _load_conversation_ref(self) -> str | None:
        path = self.conversation_state_path
        if path is None or not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        value = payload.get("conversationRef") if isinstance(payload, dict) else None
        if isinstance(value, str) and 0 < len(value) <= 512:
            return value
        return None

    def _persist_conversation_ref(self, value: str) -> None:
        path = self.conversation_state_path
        if path is None or not value or len(value) > 512:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"conversationRef": value}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            # A browser session must remain usable even if local state storage
            # is temporarily unavailable (read-only media, locked profile, ...).
            return

    def _clear_conversation_ref(self) -> None:
        path = self.conversation_state_path
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return

    @staticmethod
    def _failed(message: str) -> AgentResult:
        return AgentResult(
            status="failed", summary="ChatGPT Web request failed", events=[],
            changed_files=[], test_commands=[], error=message,
        )
