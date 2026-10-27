"""Per-turn GPT/Claude routing without changing the canonical conversation.

Codex is an action-capable agent, not a text model; it is intentionally
unavailable here until its sandbox/approval app-server adapter is installed.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from threading import Event
from typing import Any

import httpx

from app.conversations.providers import ConversationProviderError

_CHOICES = frozenset({"auto", "gpt", "claude", "codex", "personal_llm", "ollama", "chatgpt_web"})


def normalize_provider(value: str) -> str:
    selected = value.strip().lower()
    if selected not in _CHOICES:
        raise ValueError("unsupported conversation provider")
    return selected


class BlockedProvider:
    """Explicit failures never silently switch a manually selected model."""

    def __init__(self, name: str, reason: str):
        self.provider_name = name
        self.model = None
        self.reason = reason

    def stream(self, messages, **kwargs) -> Iterator[str]:
        raise ConversationProviderError(self.reason, code=f"{self.provider_name}_unavailable")
        yield ""


class OpenAIResponsesProvider:
    provider_name = "gpt"

    def __init__(
        self, *, api_key: str, model: str = "gpt-6.1-sol",
        base_url: str = "https://api.openai.com/v1/responses",
        transport: httpx.BaseTransport | None = None,
    ):
        self._key = api_key
        self.model = model
        self.base_url = base_url
        self.transport = transport

    def stream(
        self, messages: list[dict[str, str]], *, cancel_event: Event | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        inputs = [
            {"role": m["role"], "content": m["content"]}
            for m in messages if m.get("role") in {"system", "user", "assistant"}
            and m.get("content")
        ]
        if not inputs:
            raise ConversationProviderError("GPT 요청에 대화가 없습니다.", code="gpt_empty_context")
        try:
            with httpx.Client(timeout=180.0, transport=self.transport) as client:  # noqa: SIM117
                with client.stream(
                    "POST", self.base_url,
                    headers={
                        "Authorization": f"Bearer {self._key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self.model, "input": inputs, "stream": True,
                          "max_output_tokens": 2048},
                ) as response:
                    if response.status_code != 200:
                        raise ConversationProviderError(
                            f"GPT API가 HTTP {response.status_code}을 반환했습니다.",
                            code=f"gpt_http_{response.status_code}",
                        )
                    yield from _sse_deltas(
                        response.iter_lines(), "response.output_text.delta",
                        "delta", cancel_event, "gpt",
                    )
        except httpx.HTTPError as exc:
            raise ConversationProviderError(
                "GPT 연결 오류. API 키와 네트워크를 확인해 주세요.",
                code="gpt_connection_failed",
            ) from exc


class ClaudeMessagesProvider:
    provider_name = "claude"

    def __init__(
        self, *, api_key: str, model: str = "claude-sonnet-5-5",
        base_url: str = "https://api.anthropic.com/v1/messages",
        transport: httpx.BaseTransport | None = None,
    ):
        self._key = api_key
        self.model = model
        self.base_url = base_url
        self.transport = transport

    def stream(
        self, messages: list[dict[str, str]], *, cancel_event: Event | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        system = []
        turns: list[dict[str, str]] = []
        for msg in messages:
            text = msg.get("content", "").strip()
            if not text:
                continue
            if msg.get("role") == "system":
                system.append(text)
            elif msg.get("role") in ("user", "assistant"):
                role = msg["role"]
                if turns and turns[-1]["role"] == role:
                    turns[-1]["content"] += "\n\n" + text
                else:
                    turns.append({"role": role, "content": text})
        if not turns:
            raise ConversationProviderError("Claude 요청에 대화가 없습니다.", code="claude_empty_context")
        try:
            with httpx.Client(timeout=180.0, transport=self.transport) as client:  # noqa: SIM117
                with client.stream(
                    "POST", self.base_url,
                    headers={
                        "x-api-key": self._key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model, "max_tokens": 2048,
                        "messages": turns,
                        "system": "\n\n".join(system) or "Respond helpfully and accurately.",
                        "stream": True,
                    },
                ) as response:
                    if response.status_code != 200:
                        raise ConversationProviderError(
                            f"Claude API가 HTTP {response.status_code}을 반환했습니다.",
                            code=f"claude_http_{response.status_code}",
                        )
                    yield from _sse_deltas(
                        response.iter_lines(), "content_block_delta",
                        "delta.text", cancel_event, "claude",
                    )
        except httpx.HTTPError as exc:
            raise ConversationProviderError(
                "Claude 연결 오류. API 키와 네트워크를 확인해 주세요.",
                code="claude_connection_failed",
            ) from exc


def _sse_deltas(
    lines: Iterator[str], event_type: str, value_path: str,
    cancel_event: Event | None, provider: str,
) -> Iterator[str]:
    for line in lines:
        if cancel_event is not None and cancel_event.is_set():
            raise ConversationProviderError(
                "요청을 취소했습니다.", code="conversation_cancelled",
            )
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("type") == "error" or data.get("type") in {"response.failed", "message_stop_error"}:
            raise ConversationProviderError(
                f"{provider} 모델 생성이 실패했습니다.", code=f"{provider}_generation_failed",
            )
        if data.get("type") != event_type:
            continue
        value = data
        for key in value_path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if isinstance(value, str) and value:
            yield value


class ProviderHub:
    """Routes each request independently; provider selection is never global mutable state."""

    def __init__(self, auto_provider: Any, *, personal_llm: Any = None,
                 ollama: Any = None, chatgpt_web: Any = None,
                 openai_key: str | None = None, claude_key: str | None = None,
                 openai_model: str | None = None, claude_model: str | None = None):
        self.auto_provider = auto_provider
        self.gpt = OpenAIResponsesProvider(
            api_key=openai_key or "",
            model=openai_model or "gpt-6.1-sol",
        )
        self.claude = ClaudeMessagesProvider(
            api_key=claude_key or "",
            model=claude_model or "claude-sonnet-5-5",
        )
        self.available = {
            "gpt": bool(openai_key),
            "claude": bool(claude_key),
            "personal_llm": personal_llm is not None,
            "ollama": ollama is not None,
            "chatgpt_web": chatgpt_web is not None,
            "codex": False,
        }
        self.providers = {"gpt": self.gpt, "claude": self.claude,
                          "personal_llm": personal_llm, "ollama": ollama,
                          "chatgpt_web": chatgpt_web}

    @classmethod
    def from_environment(cls, auto_provider: Any, **kwargs) -> ProviderHub:
        return cls(
            auto_provider,
            openai_key=os.getenv("OPENAI_API_KEY"),
            claude_key=os.getenv("ANTHROPIC_API_KEY"),
            openai_model=os.getenv("GLEAVE_OPENAI_MODEL"),
            claude_model=os.getenv("GLEAVE_CLAUDE_MODEL"),
            **kwargs,
        )

    def select(self, choice: str, messages: list[dict[str, str]]) -> Any:
        choice = normalize_provider(choice)
        if choice == "codex":
            return BlockedProvider(
                "codex",
                "Codex는 프로젝트에 연결된 코드 에이전트입니다. "
                "Gleave의 Codex 작업 API를 통해 실행해 주세요.",
            )
        if choice == "auto":
            # Rule-based first implementation. Formal cost/quality router follows.
            last_user = next((m["content"] for m in reversed(messages)
                              if m.get("role") == "user"), "").lower()
            coding = any(marker in last_user for marker in
                         ("개발", "코드", "버그", "리팩토링", "구현", "refactor", "code", "bug"))
            if coding and self.available["claude"]:
                return self.claude
            if self.available["gpt"]:
                return self.gpt
            if self.available["claude"]:
                return self.claude
            return self.auto_provider
        if not self.available.get(choice, False):
            if choice == "codex":
                return BlockedProvider("codex", "Codex 작업 런타임은 아직 연결되지 않았습니다.")
            return BlockedProvider(choice, f"{choice} 연결 설정을 먼저 완료해 주세요.")
        return self.providers[choice]

    def catalog(self) -> list[dict[str, object]]:
        rows = [{"id": "auto", "label": "Auto", "type": "route", "available": True, "model": None}]
        for key, label, kind in (
            ("gpt", "GPT", "chat"), ("claude", "Claude", "chat"),
            ("codex", "Codex", "agent"), ("personal_llm", "Personal LLM", "local"),
            ("ollama", "Ollama", "local"), ("chatgpt_web", "GPT Web", "chat"),
        ):
            provider = self.providers.get(key)
            rows.append({
                "id": key, "label": label, "type": kind,
                "available": self.available.get(key, False),
                "model": getattr(provider, "model", None),
            })
        return rows
