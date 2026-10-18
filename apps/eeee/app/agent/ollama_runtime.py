from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

import httpx


class OllamaRuntimeError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OllamaStatus:
    status: str
    model: str | None
    error_code: str | None = None
    message: str | None = None


class OllamaRuntime:
    """Small synchronous Ollama adapter used by the Core conversation service."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str | None,
        connect_timeout_seconds: float = 3.0,
        generation_timeout_seconds: float = 120.0,
        context_tokens: int = 8192,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("Ollama base URL is required")
        if connect_timeout_seconds <= 0 or generation_timeout_seconds <= 0:
            raise ValueError("Ollama timeouts must be positive")
        if context_tokens <= 0:
            raise ValueError("Ollama context tokens must be positive")
        self.base_url = base_url.rstrip("/")
        self.model = model.strip() if model else None
        self.connect_timeout_seconds = connect_timeout_seconds
        self.generation_timeout_seconds = generation_timeout_seconds
        self.context_tokens = context_tokens
        self.transport = transport

    def status(self) -> OllamaStatus:
        if not self.model:
            return OllamaStatus(
                status="model_missing",
                model=None,
                error_code="ollama_model_missing",
                message="Ollama model is not configured",
            )
        try:
            with self._client() as client:
                response = client.get("/api/tags")
            if response.status_code >= 400:
                return OllamaStatus(
                    status="unavailable",
                    model=self.model,
                    error_code="ollama_unavailable",
                    message=f"Ollama returned HTTP {response.status_code}",
                )
            data = response.json()
            models = data.get("models", []) if isinstance(data, Mapping) else []
            names = {
                item.get("name")
                for item in models
                if isinstance(item, Mapping) and isinstance(item.get("name"), str)
            }
            if names and self.model not in names:
                return OllamaStatus(
                    status="model_missing",
                    model=self.model,
                    error_code="ollama_model_missing",
                    message=f"Ollama model is not installed: {self.model}",
                )
            return OllamaStatus(status="ready", model=self.model)
        except (httpx.ConnectError, httpx.NetworkError, OSError) as exc:
            return OllamaStatus(
                status="unavailable",
                model=self.model,
                error_code="ollama_unavailable",
                message=str(exc) or "Ollama is unavailable",
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            return OllamaStatus(
                status="unavailable",
                model=self.model,
                error_code="ollama_timeout",
                message=str(exc) or "Ollama status check timed out",
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return OllamaStatus(
                status="unavailable",
                model=self.model,
                error_code="ollama_invalid_response",
                message=str(exc) or "Ollama returned invalid status",
            )

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[str]:
        if not self.model:
            raise OllamaRuntimeError(
                "Ollama model is not configured", code="ollama_model_missing"
            )
        if cancel_event is not None and cancel_event.is_set():
            raise OllamaRuntimeError("Ollama request was cancelled", code="ollama_cancelled")
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"num_ctx": self.context_tokens},
        }
        try:
            with self._client() as client:
                with client.stream("POST", "/api/chat", json=payload) as response:
                    if response.status_code >= 400:
                        code = (
                            "ollama_model_missing"
                            if response.status_code == 404
                            else "ollama_unavailable"
                        )
                        raise OllamaRuntimeError(
                            f"Ollama returned HTTP {response.status_code}", code=code
                        )
                    for line in response.iter_lines():
                        if cancel_event is not None and cancel_event.is_set():
                            raise OllamaRuntimeError(
                                "Ollama request was cancelled", code="ollama_cancelled"
                            )
                        if not line:
                            continue
                        try:
                            data: Any = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise OllamaRuntimeError(
                                "Ollama returned malformed JSON", code="ollama_invalid_response"
                            ) from exc
                        if not isinstance(data, Mapping):
                            raise OllamaRuntimeError(
                                "Ollama response must be an object", code="ollama_invalid_response"
                            )
                        if isinstance(data.get("error"), str):
                            raise OllamaRuntimeError(
                                data["error"],
                                code="ollama_model_missing"
                                if "model" in data["error"].lower()
                                else "ollama_unavailable",
                            )
                        message = data.get("message")
                        content = message.get("content") if isinstance(message, Mapping) else None
                        if content is None:
                            content = data.get("response")
                        if content is not None and not isinstance(content, str):
                            raise OllamaRuntimeError(
                                "Ollama response content must be text",
                                code="ollama_invalid_response",
                            )
                        if content:
                            yield content
        except OllamaRuntimeError:
            raise
        except httpx.TimeoutException as exc:
            raise OllamaRuntimeError(
                str(exc) or "Ollama request timed out", code="ollama_timeout"
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError, OSError) as exc:
            raise OllamaRuntimeError(
                str(exc) or "Ollama is unavailable", code="ollama_unavailable"
            ) from exc

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(
                self.generation_timeout_seconds,
                connect=self.connect_timeout_seconds,
            ),
            transport=self.transport,
        )
