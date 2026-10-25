"""Adapt the durable conversation provider contract to the legacy agent lane."""

from __future__ import annotations

from typing import Any

from app.agent.protocol import AgentRequest, AgentResult


class ConversationProviderAgentRuntime:
    """Run a selected conversation provider through ``AgentRuntime``."""

    def __init__(self, provider: Any) -> None:
        self.provider = provider

    def run(self, request: AgentRequest) -> AgentResult:
        try:
            answer = "".join(
                self.provider.stream(
                    _prompt_messages(request.prompt),
                    cancel_event=None,
                    user_id=request.user_id,
                    request_id=request.run_id,
                    conversation_id=request.conversation_id or "desktop-default",
                )
            ).strip()
        except Exception as exc:  # noqa: BLE001 - provider boundary normalizes backend failures
            return AgentResult(
                status="unavailable",
                summary="",
                events=[
                    {
                        "type": "provider.unavailable",
                        "provider": getattr(self.provider, "active_provider_name", "conversation"),
                    }
                ],
                changed_files=[],
                test_commands=[],
                error=str(exc) or "conversation provider is unavailable",
                error_code=getattr(exc, "code", None) or "assistant_provider_unavailable",
            )

        if not answer:
            return AgentResult(
                status="failed",
                summary="",
                events=[],
                changed_files=[],
                test_commands=[],
                error="conversation provider returned an empty response",
                error_code="provider_empty_response",
            )
        return AgentResult(
            status="completed",
            summary=answer,
            events=[
                {
                    "type": "provider.selected",
                    "provider": getattr(self.provider, "active_provider_name", "conversation"),
                    "model": getattr(self.provider, "active_model", None),
                }
            ],
            changed_files=[],
            test_commands=[],
            error=None,
        )


__all__ = ["ConversationProviderAgentRuntime"]


_PERSONAL_LLM_SYSTEM_PROMPT = (
    "너는 EEEE라는 개인 비서야. 사용자의 현재 요청에 바로 답해. "
    "한국어로 자연스럽고 짧게 답해. 내부 라우팅·모델·JSON을 설명하지 마."
)


def _prompt_messages(prompt: str) -> list[dict[str, str]]:
    """Keep the small personal model focused on the current user turn.

    ``PersonalSecretary`` also embeds the durable transcript in its prompt for
    the bounded local runtime.  Passing that JSON transcript to the compact
    personal model makes it imitate an old assistant answer instead of
    answering the current turn, so the provider receives a stable instruction
    plus only the current user request.  The personal service owns the user's
    profile and conversation scope through the typed request metadata.
    """
    marker = "현재 사용자 요청:"
    current = prompt.rsplit(marker, 1)[-1] if marker in prompt else prompt
    current = current.strip()
    if not current:
        return [{"role": "user", "content": prompt}]
    return [
        {"role": "system", "content": _PERSONAL_LLM_SYSTEM_PROMPT},
        {"role": "user", "content": current},
    ]
