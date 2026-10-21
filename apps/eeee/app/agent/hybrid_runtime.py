"""Provider-neutral hybrid runtime for EEEE's general conversation lane."""

from __future__ import annotations

import re

from app.agent.protocol import AgentRequest, AgentResult, AgentRuntime
from app.agent.provider_policy import ProviderPolicy


def _current_user_request(prompt: str) -> str:
    for marker in ("현재 사용자 요청:", "사용자 요청:"):
        if marker in prompt:
            return prompt.rsplit(marker, 1)[1].strip()[:2_000]
    return prompt.strip()[:2_000]


class HybridAssistantRuntime:
    """Use local reasoning first for chat and Web reasoning for deep work."""

    def __init__(
        self,
        *,
        local: AgentRuntime | None = None,
        web: AgentRuntime | None = None,
        builtin: AgentRuntime | None = None,
        policy: ProviderPolicy | None = None,
    ) -> None:
        self.local = local
        self.web = web
        self.builtin = builtin
        self.policy = policy or ProviderPolicy()

    def run(self, request: AgentRequest) -> AgentResult:
        decision = self.policy.choose(
            _current_user_request(request.prompt),
            local_available=_provider_is_available(self.local),
            web_available=_provider_is_available(self.web),
            builtin_available=self.builtin is not None,
        )
        if decision.provider == "builtin":
            assert self.builtin is not None
            return _annotate(
                self.builtin.run(request), "builtin", decision.reason
            )
        if decision.provider == "unavailable":
            return AgentResult(
                status="unavailable", summary="EEEE AI provider is unavailable",
                events=[{"type": "provider.unavailable", "reason": decision.reason}],
                changed_files=[], test_commands=[], error="no local or ChatGPT Web provider is configured",
            )
        primary = self.local if decision.provider == "local" else self.web
        fallback = self.web if decision.provider == "local" else self.local
        assert primary is not None
        response = primary.run(request)
        if response.status == "unavailable" and self.builtin is not None and decision.reason in {
            "simple_request", "web_primary"
        }:
            return _annotate(
                self.builtin.run(request), "builtin", "builtin_fallback"
            )
        # A routine turn must never silently jump to the slow Web/GPT lane
        # just because the local model had a transient failure.  The user
        # chose the hybrid contract: Web is for complex work, not a hidden
        # fallback for greetings or everyday chat.
        if (
            response.status not in {"unavailable"}
            or fallback is None
            or decision.reason == "simple_request"
        ):
            return _annotate(response, decision.provider, decision.reason)
        fallback_response = fallback.run(request)
        return _annotate(fallback_response, "web" if decision.provider == "local" else "local", "provider_fallback")


def _provider_is_available(provider: AgentRuntime | None) -> bool:
    if provider is None:
        return False
    status_method = getattr(provider, "status", None)
    if not callable(status_method):
        return True
    try:
        status = status_method()
    except Exception:
        return False
    return getattr(status, "status", None) == "ready"


def _annotate(response: AgentResult, provider: str, reason: str) -> AgentResult:
    return AgentResult(
        status=response.status,
        summary=response.summary,
        events=[*response.events, {"type": "provider.selected", "provider": provider, "reason": reason}],
        changed_files=response.changed_files,
        test_commands=response.test_commands,
        error=response.error,
    )


class FastLocalConversationRuntime:
    """Tiny zero-dependency local lane for routine conversational turns.

    This is deliberately not presented as a general LLM.  It keeps common
    greetings and acknowledgements instant on a fresh installation while an
    installed Ollama model remains the richer local provider when available.
    Complex work is still selected for the Web/ISEOL lane by ``ProviderPolicy``.
    """

    _RESPONSES = (
        (("안녕", "하이", "hello", "hi"), "안녕! 😊 오늘은 뭐 도와줄까?"),
        (("고마워", "감사", "thanks", "thank"), "천만에! 필요하면 언제든 말해줘."),
        (("잘자", "굿나잇", "good night"), "잘 자! 다음에 이어서 도와줄게."),
        (("뭐해", "어디야", "상태"), "여기서 대기 중이야. 필요한 일을 말해줘."),
        (("할 수 있어", "할수 있어", "가능해", "뭐 할 수", "무엇을 할 수", "capable"),
         "나는 기본 대화부터 일정·기억·문서 정리까지 도와줄 수 있어. 프로젝트를 만들 때는 ISEOL이 기획·개발·QA를 맡고, 필요한 플러그인이 있으면 연결해서 더 정확하게 처리해."),
        (("ㅇㅇ", "알겠어", "오케이", "좋아", "okay", "ok"),
         "좋아, 이해했어. 다음에 할 일을 말해줘."),
        (("왜 말 안", "왜 대답", "벙어리", "말해줘"),
         "지금 바로 대답할게. 하고 싶은 일을 자연스럽게 말해주면 내가 필요한 도구와 순서를 판단해서 진행할게."),
    )

    def run(self, request: AgentRequest) -> AgentResult:
        # General conversation arrives through PersonalSecretary as a prompt
        # containing history, preferences, and routing guidance. Matching
        # against the whole prompt lets old turns or the guidance itself win
        # over the user's current sentence (for example every turn becoming
        # the capability answer). Only the current request is conversational
        # input; the rest is context.
        normalized = re.sub(
            r"\s+", " ", self._current_request(request.prompt).casefold()
        ).strip()
        if not ProviderPolicy.is_builtin_eligible(normalized):
            return AgentResult(
                status="unavailable",
                summary="",
                events=[{"type": "provider.unavailable", "provider": "builtin"}],
                changed_files=[],
                test_commands=[],
                error="builtin provider supports only bounded basic conversation",
            )
        for phrases, response in self._RESPONSES:
            if any(phrase in normalized for phrase in phrases):
                return AgentResult(
                    status="completed",
                    summary=response,
                    events=[{"type": "local.fast-conversation", "provider": "builtin"}],
                    changed_files=[], test_commands=[], error=None,
                )
        return AgentResult(
            status="completed",
            summary="응, 듣고 있어. 지금 하려는 일이나 궁금한 점을 한 문장으로 말해주면 바로 같이 정리할게.",
            events=[{"type": "local.fast-conversation.generic", "provider": "builtin"}],
            changed_files=[], test_commands=[], error=None,
        )

    @staticmethod
    def _current_request(prompt: str) -> str:
        return _current_user_request(prompt)
