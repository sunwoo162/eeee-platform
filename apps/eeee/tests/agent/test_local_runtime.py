from pathlib import Path

from app.agent.local_runtime import LocalAction, LocalAgentRuntime, LocalConversationRuntime, LocalModelResponse, OllamaBackend
from app.agent.protocol import AgentRequest


class ScriptedBackend:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []

    def complete(self, prompt, *, workspace, context):
        self.prompts.append(prompt)
        return next(self.responses)


def request(workspace: Path) -> AgentRequest:
    return AgentRequest(
        prompt="Build a verified todo app",
        workspace=workspace,
        allowed_actions=["workspace.write", "command.test"],
        run_id="local-run-1",
    )


def test_local_runtime_executes_bounded_write_and_test_loop(tmp_path):
    backend = ScriptedBackend([
        LocalModelResponse(
            summary="Created the Todo model",
            actions=[LocalAction(kind="write", path="src/todo.js", content="export const todo = {};"),
                     LocalAction(kind="run", argv=["python", "-c", "print('ok')"])],
            done=True,
        )
    ])
    runtime = LocalAgentRuntime(backend=backend, workspace_root=tmp_path)

    result = runtime.run(request(tmp_path))

    assert result.status == "completed"
    assert result.changed_files == ["src/todo.js"]
    assert result.test_commands == ["python -c print('ok')"]
    assert (tmp_path / "src" / "todo.js").read_text(encoding="utf-8") == "export const todo = {};"
    assert any(event.get("evidenceId") for event in result.events)


def test_local_runtime_blocks_path_escape_and_does_not_write(tmp_path):
    backend = ScriptedBackend([
        LocalModelResponse(
            summary="attempted escape",
            actions=[LocalAction(kind="write", path="../outside.txt", content="unsafe")],
            done=True,
        )
    ])
    runtime = LocalAgentRuntime(backend=backend, workspace_root=tmp_path)

    result = runtime.run(request(tmp_path))

    assert result.status == "failed"
    assert "outside" in (result.error or "").lower()
    assert not (tmp_path.parent / "outside.txt").exists()


def test_local_runtime_does_not_complete_after_a_failed_command(tmp_path):
    existing = tmp_path / "src" / "existing.js"
    existing.parent.mkdir()
    existing.write_text("before", encoding="utf-8")
    backend = ScriptedBackend([
        LocalModelResponse(
            summary="변경 후 검증",
            actions=[
                LocalAction(kind="write", path="src/existing.js", content="after"),
                LocalAction(kind="write", path="src/new.js", content="new"),
                LocalAction(kind="run", argv=["python", "-c", "raise SystemExit(3)"]),
            ],
            done=True,
        )
    ])
    runtime = LocalAgentRuntime(backend=backend, workspace_root=tmp_path)

    result = runtime.run(request(tmp_path))

    assert result.status == "failed"
    assert "failed" in (result.error or "").lower()
    assert existing.read_text(encoding="utf-8") == "before"
    assert not (tmp_path / "src" / "new.js").exists()
    assert result.changed_files == []


def test_local_runtime_rolls_back_when_reasoning_reaches_step_limit(tmp_path):
    backend = ScriptedBackend([
        LocalModelResponse(
            summary="아직 진행 중",
            actions=[LocalAction(kind="write", path="src/partial.js", content="partial")],
            done=False,
            next_prompt="계속 진행해",
        )
    ])
    runtime = LocalAgentRuntime(backend=backend, workspace_root=tmp_path, max_steps=1)

    result = runtime.run(request(tmp_path))

    assert result.status == "failed"
    assert "maximum local reasoning steps" in (result.error or "").lower()
    assert not (tmp_path / "src" / "partial.js").exists()
    assert result.changed_files == []


def test_ollama_backend_converts_local_json_response(monkeypatch, tmp_path):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '{"summary":"done","actions":[],"done":true}'}}

    calls = []
    monkeypatch.setattr("app.agent.local_runtime.httpx.post", lambda *args, **kwargs: (calls.append((args, kwargs)) or Response()))
    result = OllamaBackend(model="qwen2.5-coder:7b").complete(
        "Build it", workspace=tmp_path, context=[]
    )

    assert result.done is True
    assert calls[0][1]["json"]["model"] == "qwen2.5-coder:7b"
    assert calls[0][1]["json"]["stream"] is False


def test_ollama_backend_adapts_conversational_finish_response(monkeypatch, tmp_path):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '{"action":"finish","response":"안녕하세요! 무엇을 도와드릴까요?"}'}}

    monkeypatch.setattr("app.agent.local_runtime.httpx.post", lambda *args, **kwargs: Response())

    result = OllamaBackend(model="qwen3:4b").complete(
        "안녕", workspace=tmp_path, context=[]
    )

    assert result.summary == "안녕하세요! 무엇을 도와드릴까요?"
    assert result.done is True
    assert result.actions[0].kind == "finish"


def test_ollama_backend_plain_conversation_does_not_request_json(monkeypatch, tmp_path):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "점심은 가볍게 국수나 샌드위치가 좋겠어요."}}

    calls = []
    monkeypatch.setattr(
        "app.agent.local_runtime.httpx.post",
        lambda *args, **kwargs: (calls.append((args, kwargs)) or Response()),
    )

    result = OllamaBackend(model="qwen2.5:1.5b").complete_text(
        "오늘 점심 뭐 먹을까?", workspace=tmp_path, context=[]
    )

    payload = calls[0][1]["json"]
    assert result == "점심은 가볍게 국수나 샌드위치가 좋겠어요."
    assert payload["stream"] is False
    assert "format" not in payload
    assert "자연스러운 한국어" in payload["messages"][0]["content"]
    assert "Observations:" not in payload["messages"][1]["content"]


def test_ollama_backend_plain_conversation_keeps_model_warm_and_bounds_output(monkeypatch, tmp_path):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "응, 바로 도와줄게."}}

    calls = []
    monkeypatch.setattr(
        "app.agent.local_runtime.httpx.post",
        lambda *args, **kwargs: (calls.append((args, kwargs)) or Response()),
    )

    OllamaBackend(model="qwen3:4b").complete_text(
        "안녕", workspace=tmp_path, context=[{"ignored": True}]
    )

    payload = calls[0][1]["json"]
    assert payload["keep_alive"] == "10m"
    assert payload["think"] is True
    assert payload["options"] == {"num_predict": 2048, "temperature": 0.4}
    assert payload["messages"][1]["content"] == "안녕"


def test_local_conversation_lane_returns_text_without_executing_actions(tmp_path):
    class ConversationBackend:
        def complete(self, prompt, *, workspace, context):
            assert "일반 대화만 처리해" in prompt
            return LocalModelResponse(
                summary="도와줄 수 있는 일을 함께 정리해볼게.",
                actions=[LocalAction(kind="run", argv=["not-used"])],
                done=True,
            )

    result = LocalConversationRuntime(backend=ConversationBackend()).run(
        AgentRequest("무엇을 도와줄 수 있어?", tmp_path, [], "conversation-1")
    )

    assert result.status == "completed"
    assert result.summary == "도와줄 수 있는 일을 함께 정리해볼게."
    assert result.changed_files == []
    assert result.test_commands == []


def test_local_conversation_lane_uses_plain_text_backend_when_available(tmp_path):
    class PlainTextBackend:
        def __init__(self):
            self.prompts = []

        def complete_text(self, prompt, *, workspace, context):
            self.prompts.append(prompt)
            return "그럴 수 있어. 수면과 식사 상태부터 같이 확인해보자."

    backend = PlainTextBackend()
    result = LocalConversationRuntime(backend=backend).run(
        AgentRequest("내가 왜 피곤한지 설명해줘.", tmp_path, [], "conversation-plain")
    )

    assert result.status == "completed"
    assert result.summary == "그럴 수 있어. 수면과 식사 상태부터 같이 확인해보자."
    assert "Return exactly one JSON object" not in backend.prompts[0]
    assert "일반 대화만 처리해" in backend.prompts[0]


def test_local_conversation_lane_retries_prompt_leakage_with_a_clean_turn(tmp_path):
    class PlainTextBackend:
        def __init__(self):
            self.prompts = []
            self.responses = iter([
                "EEE EEEE, 이제 1초에 한글자씩 말해요!",
                "안녕하세요! 오늘은 무엇을 도와드릴까요?",
            ])

        def complete_text(self, prompt, *, workspace, context):
            self.prompts.append(prompt)
            return next(self.responses)

    backend = PlainTextBackend()
    result = LocalConversationRuntime(backend=backend).run(
        AgentRequest("안녕", tmp_path, [], "conversation-retry")
    )

    assert result.status == "completed"
    assert result.summary == "안녕하세요! 오늘은 무엇을 도와드릴까요?"
    assert len(backend.prompts) == 2
    assert "이전 답변의 지시문을 반복하지 마" in backend.prompts[1]
    assert "사용자의 실제 마지막 문장: 안녕" in backend.prompts[1]


def test_local_conversation_lane_checks_provider_identity_only_on_current_turn(tmp_path):
    class PlainTextBackend:
        def complete_text(self, prompt, *, workspace, context):
            return "안녕하세요!"

    prompt = (
        "너는 EEEE라는 개인 비서야.\n"
        '최근 대화: [{"role":"user","content":"GPT Web을 써?"}]\n'
        "사용자 선호: {}\n관련 기억: {}\n현재 사용자 요청: 안녕"
    )
    result = LocalConversationRuntime(backend=PlainTextBackend()).run(
        AgentRequest(prompt, tmp_path, [], "conversation-history-provider")
    )

    assert result.status == "completed"
    assert result.summary == "안녕하세요!"


def test_local_conversation_lane_rejects_a_second_prompt_leakage_response(tmp_path):
    class PlainTextBackend:
        def __init__(self):
            self.calls = 0

        def complete_text(self, prompt, *, workspace, context):
            self.calls += 1
            return "EEE EEEE, 이제 1초에 한글자씩 말해요!"

    backend = PlainTextBackend()
    result = LocalConversationRuntime(backend=backend).run(
        AgentRequest("안녕", tmp_path, [], "conversation-double-leak")
    )

    assert result.status == "unavailable"
    assert "prompt leakage" in (result.error or "")
    assert backend.calls == 2


def test_local_conversation_lane_reports_provider_truthfully(tmp_path):
    class FailingBackend:
        def complete_text(self, *args, **kwargs):
            raise AssertionError("provider identity should not call the model")

    result = LocalConversationRuntime(backend=FailingBackend()).run(
        AgentRequest("지금 GPT 웹을 쓰고 있어?", tmp_path, [], "conversation-provider")
    )

    assert result.status == "completed"
    assert "GPT Web이 아니라" in result.summary
    assert result.events == [{"type": "local.conversation", "provider": "ollama"}]
