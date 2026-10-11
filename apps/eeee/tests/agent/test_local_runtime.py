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


def test_local_conversation_lane_returns_text_without_executing_actions(tmp_path):
    class ConversationBackend:
        def complete(self, prompt, *, workspace, context):
            assert "ordinary conversation only" in prompt
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
