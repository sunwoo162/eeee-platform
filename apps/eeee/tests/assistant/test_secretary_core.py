from pathlib import Path

from app.agent.hybrid_runtime import FastLocalConversationRuntime
from app.agent.protocol import AgentRequest
from app.assistant.secretary import PersonalSecretary, SecretaryContext


def test_secretary_prompt_keeps_follow_up_context_and_redacts_sensitive_memory() -> None:
    secretary = PersonalSecretary()
    context = SecretaryContext(
        conversation_id="desktop-default",
        recent_turns=[
            {"role": "user", "content": "나는 아침에 집중이 잘돼."},
            {"role": "assistant", "content": "아침 집중 작업을 우선으로 기억할게."},
        ],
        preferences={"work.time": "아침"},
        memory_context='{"memories":[{"content":"비밀번호: secret-value"}]}'
    )

    prompt = secretary.build_prompt("그럼 오늘 먼저 뭐 할까?", context)

    assert "나는 아침에 집중이 잘돼." in prompt
    assert "오늘 먼저 뭐 할까?" in prompt
    assert "work.time" in prompt
    assert "secret-value" not in prompt
    assert "비밀번호" not in prompt


def test_secretary_extracts_safe_preference_but_rejects_secret() -> None:
    secretary = PersonalSecretary()

    assert secretary.rememberable_facts("나는 아침에 집중 작업을 선호해") == [
        ("routine.focus_time", "아침")
    ]
    assert secretary.rememberable_facts("내 비밀번호는 secret-value야") == []


def test_fast_local_conversation_does_not_repeat_one_generic_reply_for_every_request() -> None:
    runtime = FastLocalConversationRuntime()
    first = runtime.run(AgentRequest("내일 회의 정리 도와줘", Path.cwd(), [], "turn-1"))
    second = runtime.run(AgentRequest("오늘 점심 뭐 먹을까?", Path.cwd(), [], "turn-2"))

    assert first.status == "completed"
    assert second.status == "completed"
    assert first.summary != second.summary
    assert "회의" in first.summary
    assert "점심" in second.summary
