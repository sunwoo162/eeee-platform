from pathlib import Path

import pytest

from app.agent.hybrid_runtime import FastLocalConversationRuntime
from app.agent.protocol import AgentRequest


def test_builtin_local_lane_answers_common_chat_without_web():
    runtime = FastLocalConversationRuntime()
    result = runtime.run(AgentRequest("안녕", Path("."), [], "run-1"))

    assert result.status == "completed"
    assert "뭐 도와줄까" in result.summary
    assert result.events[0]["provider"] == "builtin"


@pytest.mark.parametrize("prompt", ["오늘 날씨 어때?", "대한민국의 수도는 어디야?", "파이썬이 뭐야?"])
def test_builtin_local_lane_rejects_weather_and_fact_questions_without_web(prompt):
    result = FastLocalConversationRuntime().run(
        AgentRequest(prompt, Path("."), [], "run-2")
    )

    assert result.status == "unavailable"
    assert result.changed_files == []
    assert result.test_commands == []


def test_builtin_local_lane_handles_capability_question_as_a_conversation():
    result = FastLocalConversationRuntime().run(
        AgentRequest("너는 어느 정도까지 할 수 있어?", Path("."), [], "run-3")
    )

    assert result.status == "completed"
    assert "대화" in result.summary
    assert "프로젝트" in result.summary


def test_builtin_local_lane_handles_acknowledgements_without_repeating_listening_message():
    result = FastLocalConversationRuntime().run(
        AgentRequest("ㅇㅇ 알겠어", Path("."), [], "run-4")
    )

    assert result.status == "completed"
    assert result.summary != "응, 듣고 있어."


def test_builtin_local_lane_matches_only_the_current_request_in_a_secretary_prompt():
    prompt = (
        "너는 EEEE라는 개인 비서야. 사용자가 무엇을 할 수 있냐고 물으면 능력을 설명해.\n"
        '최근 대화: [{"role":"user","content":"회의 정리해줘"}]\n'
        "현재 사용자 요청: 오늘 기분이 조금 가라앉았어"
    )

    result = FastLocalConversationRuntime().run(
        AgentRequest(prompt, Path("."), [], "run-context-1")
    )

    assert result.status == "completed"
    assert "기본 대화부터" not in result.summary
    assert "듣고 있어" in result.summary
