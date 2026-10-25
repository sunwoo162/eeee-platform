from pathlib import Path

from app.agent.conversation_runtime import ConversationProviderAgentRuntime
from app.agent.protocol import AgentRequest


class _PersonalProvider:
    active_provider_name = "personal_llm"
    active_model = "personal-model"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def stream(self, messages, *, cancel_event, user_id, request_id, conversation_id):
        self.calls.append(
            {
                "messages": messages,
                "user_id": user_id,
                "request_id": request_id,
                "conversation_id": conversation_id,
            }
        )
        yield "내 개인 LLM 답변"


def test_legacy_assistant_runtime_routes_general_chat_to_selected_provider() -> None:
    provider = _PersonalProvider()
    runtime = ConversationProviderAgentRuntime(provider)

    result = runtime.run(
        AgentRequest(
            prompt=(
                "너는 EEEE라는 개인 비서야. 최근 대화에는 이전 안내가 들어있어.\n"
                "현재 사용자 요청: 너 이름 뭐야"
            ),
            workspace=Path("."),
            allowed_actions=[],
            run_id="request-1",
            user_id="user-a",
            conversation_id="conversation-a",
        )
    )

    assert result.status == "completed"
    assert result.summary == "내 개인 LLM 답변"
    assert result.events[-1] == {
        "type": "provider.selected",
        "provider": "personal_llm",
        "model": "personal-model",
    }
    assert provider.calls == [
        {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "너는 EEEE라는 개인 비서야. 사용자의 현재 요청에 바로 답해. "
                        "한국어로 자연스럽고 짧게 답해. 내부 라우팅·모델·JSON을 설명하지 마."
                    ),
                },
                {"role": "user", "content": "너 이름 뭐야"},
            ],
            "user_id": "user-a",
            "request_id": "request-1",
            "conversation_id": "conversation-a",
        }
    ]
