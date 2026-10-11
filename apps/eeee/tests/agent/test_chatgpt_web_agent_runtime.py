import json
from pathlib import Path

from app.agent.chatgpt_web_agent_runtime import ChatGptWebAgentRuntime
from app.agent.protocol import AgentRequest, AgentResult
from app.config import Settings
from app.main import create_app


class FakeWebRuntime:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []

    def run(self, request):
        self.prompts.append(request.prompt)
        return AgentResult(
            status="completed",
            summary=next(self.responses),
            events=[], changed_files=[], test_commands=[], error=None,
        )


class FlakyWebRuntime(FakeWebRuntime):
    def run(self, request):
        self.prompts.append(request.prompt)
        if len(self.prompts) == 1:
            return AgentResult(
                status="unavailable", summary="ChatGPT Web bridge unavailable",
                events=[], changed_files=[], test_commands=[], error="ChatGPT Web bridge unavailable: conversation identity changed before prompt submission",
            )
        return AgentResult(
            status="completed",
            summary=json.dumps({
                "summary": "requirements recorded",
                "actions": [
                    {"kind": "write", "path": "REQUIREMENTS.md", "content": "# Requirements\n"},
                    {"kind": "finish"},
                ],
                "done": True,
            }),
            events=[], changed_files=[], test_commands=[], error=None,
        )


class PendingSubmissionWebRuntime(FakeWebRuntime):
    def run(self, request):
        self.prompts.append(request.prompt)
        if len(self.prompts) == 1:
            return AgentResult(
                status="failed", summary="ChatGPT Web request failed", events=[],
                changed_files=[], test_commands=[],
                error="No pending ChatGPT submission is available for structured result reading: pending-submission-missing",
            )
        return AgentResult(
            status="completed",
            summary=json.dumps({
                "summary": "recovered",
                "actions": [{"kind": "finish"}],
                "done": True,
            }),
            events=[], changed_files=[], test_commands=[], error=None,
        )


def test_chatgpt_web_agent_applies_structured_workspace_actions(tmp_path: Path):
    response = json.dumps({
        "summary": "requirements recorded",
        "actions": [
            {"kind": "write", "path": "REQUIREMENTS.md", "content": "# Requirements\n"},
            {"kind": "finish"},
        ],
        "done": True,
    })
    web = FakeWebRuntime([response])
    (tmp_path / "project").mkdir()
    runtime = ChatGptWebAgentRuntime(web_runtime=web, workspace_root=tmp_path)

    result = runtime.run(AgentRequest(
        prompt="Record requirements",
        workspace=tmp_path / "project",
        allowed_actions=["workspace.write"],
        run_id="run-1",
    ))

    assert result.status == "completed"
    assert "REQUIREMENTS.md" in result.changed_files
    assert (tmp_path / "project" / "REQUIREMENTS.md").read_text(encoding="utf-8") == "# Requirements\n"
    assert "JSON" in web.prompts[0]
    assert "finish" in web.prompts[0]
    assert "done:true" in web.prompts[0]


def test_chatgpt_web_agent_rejects_non_structured_response(tmp_path: Path):
    web = FakeWebRuntime(["I changed the file for you."])
    (tmp_path / "project").mkdir()
    runtime = ChatGptWebAgentRuntime(web_runtime=web, workspace_root=tmp_path)

    result = runtime.run(AgentRequest(
        prompt="Do work",
        workspace=tmp_path / "project",
        allowed_actions=["workspace.write"],
        run_id="run-2",
    ))

    assert result.status == "failed"
    assert "JSON" in (result.error or "")


def test_chatgpt_web_agent_retries_one_transient_web_failure(tmp_path: Path):
    web = FlakyWebRuntime([])
    (tmp_path / "project").mkdir()
    runtime = ChatGptWebAgentRuntime(web_runtime=web, workspace_root=tmp_path)

    result = runtime.run(AgentRequest(
        prompt="Record requirements",
        workspace=tmp_path / "project",
        allowed_actions=["workspace.write"],
        run_id="run-retry",
    ))

    assert result.status == "completed"
    assert len(web.prompts) == 2


def test_chatgpt_web_agent_retries_pending_submission_race(tmp_path: Path):
    web = PendingSubmissionWebRuntime([])
    (tmp_path / "project").mkdir()
    runtime = ChatGptWebAgentRuntime(web_runtime=web, workspace_root=tmp_path)

    result = runtime.run(AgentRequest(
        prompt="Recover from a browser race",
        workspace=tmp_path / "project",
        allowed_actions=["workspace.write"],
        run_id="run-pending-race",
    ))

    assert result.status == "completed"
    assert len(web.prompts) == 2


def test_chatgpt_web_is_used_as_iseol_agent_runtime_when_enabled(tmp_path: Path):
    application = create_app(Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
        chatgpt_web_enabled=True,
        chatgpt_web_bridge_url="http://127.0.0.1:47831",
        claim_latch_auto_start=False,
    ))

    handler = application.state.kernel.router.registry.resolve("project-execution").handler

    assert handler.agent_runtime.__class__.__name__ == "ChatGptWebAgentRuntime"
    assert handler.agent_runtime.max_parallelism == 1
