from pathlib import Path

from app.agent.hybrid_runtime import FastLocalConversationRuntime
from app.agent.protocol import AgentRequest


def test_builtin_local_lane_answers_common_chat_without_web():
    runtime = FastLocalConversationRuntime()
    result = runtime.run(AgentRequest("안녕", Path("."), [], "run-1"))

    assert result.status == "completed"
    assert "뭐 도와줄까" in result.summary
    assert result.events[0]["provider"] == "builtin"


def test_builtin_local_lane_answers_unknown_chat_without_web():
    result = FastLocalConversationRuntime().run(
        AgentRequest("오늘 날씨 어때?", Path("."), [], "run-2")
    )

    assert result.status == "completed"
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
