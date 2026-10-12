"""Provider-neutral hybrid runtime for EEEE's general conversation lane."""

from __future__ import annotations

import re

from app.agent.protocol import AgentRequest, AgentResult, AgentRuntime
from app.agent.provider_policy import ProviderPolicy


class HybridAssistantRuntime:
    """Use local reasoning first for chat and Web reasoning for deep work."""

    def __init__(
        self,
        *,
        local: AgentRuntime | None = None,
        web: AgentRuntime | None = None,
        policy: ProviderPolicy | None = None,
    ) -> None:
        self.local = local
        self.web = web
        self.policy = policy or ProviderPolicy()

    def run(self, request: AgentRequest) -> AgentResult:
        decision = self.policy.choose(
            request.prompt,
            local_available=self.local is not None,
            web_available=self.web is not None,
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
        normalized = re.sub(r"\s+", " ", request.prompt.casefold()).strip()
        for phrases, response in self._RESPONSES:
            if any(phrase in normalized for phrase in phrases):
                return AgentResult(
                    status="completed",
                    summary=response,
                    events=[{"type": "local.fast-conversation", "provider": "builtin"}],
                    changed_files=[], test_commands=[], error=None,
                )
        # Keep ordinary conversation local and immediate. Complex work is
        # routed to the Web/ISEOL lane by ProviderPolicy; an unknown casual
        # sentence must not unexpectedly open a slow Web conversation.
        return AgentResult(
            status="completed",
            summary="응, 여기서 바로 대화할게. 하고 싶은 말을 편하게 말해줘.",
            events=[{"type": "local.fast-conversation.generic", "provider": "builtin"}],
            changed_files=[], test_commands=[], error=None,
        )
