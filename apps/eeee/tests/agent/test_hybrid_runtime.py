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


def test_hybrid_runtime_uses_web_as_the_primary_conversation_brain():
    local = ScriptedRuntime(result("completed", "로컬 응답"))
    web = ScriptedRuntime(result("completed", "웹 응답"))

    response = HybridAssistantRuntime(local=local, web=web).run(request("사용자 요청: 안녕"))

    assert response.summary == "웹 응답"
    assert local.calls == 0
    assert web.calls == 1


def test_hybrid_runtime_uses_web_for_project_request():
    local = ScriptedRuntime(result("completed", "로컬 응답"))
    web = ScriptedRuntime(result("completed", "웹 응답"))

    response = HybridAssistantRuntime(local=local, web=web).run(request("사용자 요청: Todo 앱 만들어줘"))

    assert response.summary == "웹 응답"
    assert local.calls == 0
    assert web.calls == 1


def test_hybrid_runtime_uses_web_when_local_is_unavailable():
    local = ScriptedRuntime(result("unavailable", "", "local model is offline"))
    web = ScriptedRuntime(result("completed", "웹 응답"))

    response = HybridAssistantRuntime(local=local, web=web).run(request("사용자 요청: 안녕"))

    assert response.summary == "웹 응답"
    assert response.status == "completed"
    assert web.calls == 1


def test_hybrid_runtime_keeps_web_as_the_only_active_lane_for_simple_chat():
    local = ScriptedRuntime(result("unavailable", "", "local model is offline"))
    web = ScriptedRuntime(result("completed", "웹 응답"))

    response = HybridAssistantRuntime(local=local, web=web).run(request("사용자 요청: 오늘 점심 뭐 먹을까?"))

    assert response.summary == "웹 응답"
    assert response.status == "completed"
    assert web.calls == 1


def test_web_remains_primary_even_when_a_legacy_local_lane_is_injected():
    from app.agent.hybrid_runtime import FastLocalConversationRuntime

    web = ScriptedRuntime(result("completed", "웹 응답"))
    response = HybridAssistantRuntime(
        local=FastLocalConversationRuntime(), web=web
    ).run(request("사용자 요청: 오늘 뭐 하지?"))

    assert response.status == "completed"
    assert response.summary == "웹 응답"
    assert web.calls == 1
