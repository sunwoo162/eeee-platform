from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx


class PersonalLlmRuntimeError(RuntimeError):
    """The loopback personal LLM could not return a trustworthy answer."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PersonalLlmStatus:
    status: str
    model: str | None
    error_code: str | None = None
    message: str | None = None


class PersonalLlmRuntime:
    """Synchronous adapter for the independent personal-LLM loopback service."""

    def __init__(
        self,
        *,
        base_url: str,
        connect_timeout_seconds: float = 3.0,
        generation_timeout_seconds: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("Personal LLM base URL is required")
        if connect_timeout_seconds <= 0 or generation_timeout_seconds <= 0:
            raise ValueError("Personal LLM timeouts must be positive")
        self.base_url = base_url.rstrip("/")
        self.connect_timeout_seconds = connect_timeout_seconds
        self.generation_timeout_seconds = generation_timeout_seconds
        self.transport = transport

    def status(self) -> PersonalLlmStatus:
        try:
            with self._client() as client:
                response = client.get("/v1/model/status")
        except httpx.TimeoutException as exc:
            return PersonalLlmStatus(
                status="unavailable",
                model=None,
                error_code="personal_llm_timeout",
                message=str(exc) or "Personal LLM status check timed out",
            )
        except (httpx.HTTPError, OSError) as exc:
            return PersonalLlmStatus(
                status="unavailable",
                model=None,
                error_code="personal_llm_unavailable",
                message=str(exc) or "Personal LLM is unavailable",
            )
        if response.status_code >= 400:
            return PersonalLlmStatus(
                status="unavailable",
                model=None,
                error_code="personal_llm_http_error",
                message=f"Personal LLM returned HTTP {response.status_code}",
            )
        try:
            data = response.json()
        except (ValueError, TypeError) as exc:
            return PersonalLlmStatus(
                status="unavailable",
                model=None,
                error_code="personal_llm_invalid_response",
                message=str(exc) or "Personal LLM returned invalid status",
            )
        if not isinstance(data, Mapping):
            return PersonalLlmStatus(
                status="unavailable",
                model=None,
                error_code="personal_llm_invalid_response",
                message="Personal LLM status must be an object",
            )
        configured = data.get("configured")
        model = data.get("modelVersion")
        if not isinstance(configured, bool) or not isinstance(model, str) or not model.strip():
            return PersonalLlmStatus(
                status="unavailable",
                model=model.strip() if isinstance(model, str) and model.strip() else None,
                error_code="personal_llm_invalid_response",
                message="Personal LLM status is malformed",
            )
        if not configured:
            return PersonalLlmStatus(
                status="model_missing",
                model=model.strip(),
                error_code="personal_llm_model_missing",
                message="Personal LLM has no active model",
            )
        return PersonalLlmStatus(status="ready", model=model.strip())

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        user_id: str,
        request_id: str,
        conversation_id: str | None,
        cancel_event: threading.Event | None = None,
    ) -> str:
        if cancel_event is not None and cancel_event.is_set():
            raise PersonalLlmRuntimeError(
                "Personal LLM request was cancelled", code="conversation_cancelled"
            )
        if not user_id.strip() or not request_id.strip():
            raise PersonalLlmRuntimeError(
                "Personal LLM request identifiers must not be blank",
                code="personal_llm_invalid_request",
            )
        payload = {
            "requestId": request_id,
            "userId": user_id,
            "mode": "assistant",
            "profileRevision": 0,
            "conversationId": conversation_id,
            "messages": messages,
            "approvedMemoryIds": [],
        }
        try:
            with self._client() as client:
                response = client.post(
                    "/v1/chat",
                    json=payload,
                    headers={"X-Personal-User-Id": user_id},
                )
        except httpx.TimeoutException as exc:
            raise PersonalLlmRuntimeError(
                str(exc) or "Personal LLM request timed out",
                code="personal_llm_timeout",
            ) from exc
        except (httpx.HTTPError, OSError) as exc:
            raise PersonalLlmRuntimeError(
                str(exc) or "Personal LLM is unavailable",
                code="personal_llm_unavailable",
            ) from exc

        if cancel_event is not None and cancel_event.is_set():
            raise PersonalLlmRuntimeError(
                "Personal LLM request was cancelled", code="conversation_cancelled"
            )
        if response.status_code >= 400:
            raise PersonalLlmRuntimeError(
                _http_error_message(response), code=_http_error_code(response)
            )
        try:
            data: Any = response.json()
        except (ValueError, TypeError) as exc:
            raise PersonalLlmRuntimeError(
                str(exc) or "Personal LLM returned invalid JSON",
                code="personal_llm_invalid_response",
            ) from exc
        if not isinstance(data, Mapping):
            raise PersonalLlmRuntimeError(
                "Personal LLM response must be an object",
                code="personal_llm_invalid_response",
            )
        response_request_id = data.get("requestId")
        if response_request_id != request_id:
            raise PersonalLlmRuntimeError(
                "Personal LLM response request ID does not match",
                code="personal_llm_invalid_response",
            )
        response_user_id = data.get("userId")
        if response_user_id is not None and response_user_id != user_id:
            raise PersonalLlmRuntimeError(
                "Personal LLM response user ID does not match",
                code="personal_llm_user_scope_mismatch",
            )
        model_version = data.get("modelVersion")
        response_status = data.get("status")
        if not isinstance(model_version, str) or not model_version.strip():
            raise PersonalLlmRuntimeError(
                "Personal LLM response model version is missing",
                code="personal_llm_invalid_response",
            )
        if response_status != "completed":
            intent = data.get("intent")
            code = (
                f"personal_llm_{intent}"
                if isinstance(intent, str) and intent.strip()
                else "personal_llm_failed"
            )
            raise PersonalLlmRuntimeError(
                "Personal LLM request did not complete",
                code=code,
            )
        text = data.get("text")
        if not isinstance(text, str):
            raise PersonalLlmRuntimeError(
                "Personal LLM response text must be a string",
                code="personal_llm_invalid_response",
            )
        answer = text.strip()
        if not answer:
            raise PersonalLlmRuntimeError(
                "Personal LLM returned an empty response",
                code="personal_llm_empty_response",
            )
        return answer

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(
                self.generation_timeout_seconds,
                connect=self.connect_timeout_seconds,
            ),
            transport=self.transport,
        )


def _http_error_code(response: httpx.Response) -> str:
    try:
        data = response.json()
    except (ValueError, TypeError):
        return "personal_llm_http_error"
    if isinstance(data, Mapping):
        error = data.get("error")
        if isinstance(error, Mapping) and error.get("code") == "user_scope_mismatch":
            return "personal_llm_user_scope_mismatch"
    return "personal_llm_http_error"


def _http_error_message(response: httpx.Response) -> str:
    return f"Personal LLM returned HTTP {response.status_code}"


__all__ = [
    "PersonalLlmRuntime",
    "PersonalLlmRuntimeError",
    "PersonalLlmStatus",
]
