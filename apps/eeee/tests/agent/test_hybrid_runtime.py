from pathlib import Path

from app.agent.hybrid_runtime import HybridAssistantRuntime
from app.agent.protocol import AgentRequest, AgentResult


class ScriptedRuntime:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def run(self, request):
        self.calls += 1
        return self.result


def request(prompt: str) -> AgentRequest:
    return AgentRequest(prompt, Path("."), ["read"], "run-1")


def result(status: str, summary: str, error=None) -> AgentResult:
    return AgentResult(status, summary, [], [], [], error)


def test_hybrid_runtime_uses_local_for_simple_conversation():
    local = ScriptedRuntime(result("completed", "로컬 응답"))
    web = ScriptedRuntime(result("completed", "웹 응답"))

    response = HybridAssistantRuntime(local=local, web=web).run(request("사용자 요청: 안녕"))

    assert response.summary == "로컬 응답"
    assert local.calls == 1
    assert web.calls == 0


def test_hybrid_runtime_uses_web_for_project_request():
    local = ScriptedRuntime(result("completed", "로컬 응답"))
    web = ScriptedRuntime(result("completed", "웹 응답"))

    response = HybridAssistantRuntime(local=local, web=web).run(request("사용자 요청: Todo 앱 만들어줘"))

    assert response.summary == "웹 응답"
    assert local.calls == 0
    assert web.calls == 1


def test_hybrid_runtime_does_not_fall_back_when_local_is_unavailable():
    local = ScriptedRuntime(result("unavailable", "", "local model is offline"))
    web = ScriptedRuntime(result("completed", "웹 응답"))

    response = HybridAssistantRuntime(local=local, web=web).run(request("사용자 요청: 안녕"))

    assert response.status == "unavailable"
    assert response.error == "local model is offline"
    assert web.calls == 0


def test_hybrid_runtime_does_not_send_simple_chat_to_web_after_local_failure():
    local = ScriptedRuntime(result("unavailable", "", "local model is offline"))
    web = ScriptedRuntime(result("completed", "웹 응답"))

    response = HybridAssistantRuntime(local=local, web=web).run(request("사용자 요청: 오늘 점심 뭐 먹을까?"))

    assert response.status == "unavailable"
    assert response.error == "local model is offline"
    assert web.calls == 0


def test_builtin_local_conversation_does_not_fall_back_to_web_for_unknown_chat():
    from app.agent.hybrid_runtime import FastLocalConversationRuntime

    web = ScriptedRuntime(result("completed", "웹 응답"))
    response = HybridAssistantRuntime(
        local=FastLocalConversationRuntime(), web=web
    ).run(request("사용자 요청: 오늘 뭐 하지?"))

    assert response.status == "completed"
    assert "바로 대화할게" in response.summary
    assert web.calls == 0
