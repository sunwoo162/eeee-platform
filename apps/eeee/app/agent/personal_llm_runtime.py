from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


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


class _PersonalLlmActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: str = Field(min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = Field(default=True, alias="requiresConfirmation")

    @field_validator("parameters")
    @classmethod
    def reject_executable_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = {"command", "executable", "script", "shell"}
        if forbidden.intersection(key.casefold() for key in value):
            raise ValueError("action parameters must not contain executable fields")
        return value


class _PersonalLlmChatResponse(BaseModel):
    """Strict local copy of the wire-level response shape."""

    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str = Field(alias="requestId", min_length=1, max_length=128)
    model_version: str = Field(alias="modelVersion", min_length=1, max_length=128)
    profile_revision: int = Field(alias="profileRevision", ge=0)
    text: str = Field(default="", max_length=16_000)
    intent: str = Field(min_length=1, max_length=128)
    style_applied: bool = Field(alias="styleApplied")
    memory_used: list[str] = Field(default_factory=list, alias="memoryUsed", max_length=100)
    confidence: float = Field(ge=0, le=1)
    action_proposal: _PersonalLlmActionProposal | None = Field(
        default=None, alias="actionProposal"
    )
    needs_user_confirmation: bool = Field(alias="needsUserConfirmation")
    status: Literal["completed", "failed"]
    # The current service binds users on the request header/body and does not
    # echo userId. Accepting this optional diagnostic field lets us reject an
    # out-of-scope response if a future adapter includes it.
    user_id: str | None = Field(default=None, alias="userId", max_length=128)

    @field_validator("memory_used")
    @classmethod
    def reject_blank_memory_ids(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("memory IDs must not be blank")
        return value


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
        try:
            typed_response = _PersonalLlmChatResponse.model_validate(data)
        except ValidationError as exc:
            raise PersonalLlmRuntimeError(
                "Personal LLM response does not match its typed contract",
                code="personal_llm_invalid_response",
            ) from exc
        if typed_response.request_id != request_id:
            raise PersonalLlmRuntimeError(
                "Personal LLM response request ID does not match",
                code="personal_llm_invalid_response",
            )
        if typed_response.user_id is not None and typed_response.user_id != user_id:
            raise PersonalLlmRuntimeError(
                "Personal LLM response user ID does not match",
                code="personal_llm_user_scope_mismatch",
            )
        if typed_response.status != "completed":
            code = (
                f"personal_llm_{typed_response.intent}"
                if typed_response.intent.strip()
                else "personal_llm_failed"
            )
            raise PersonalLlmRuntimeError(
                "Personal LLM request did not complete",
                code=code,
            )
        answer = typed_response.text.strip()
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
