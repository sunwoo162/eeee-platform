from pathlib import Path
import time

from fastapi.testclient import TestClient

from app.agent.protocol import AgentResult
from app.config import Settings
from app.main import create_app


class FakeAgentRuntime:
    def run(self, request):
        agent_id = request.prompt.split("agentId=")[1].split()[0]
        changed_file = request.workspace / "src" / f"{agent_id}.js"
        changed_file.parent.mkdir(parents=True, exist_ok=True)
        changed_file.write_text(f"// {agent_id}\n", encoding="utf-8")
        return AgentResult(
            status="completed",
            summary=f"{agent_id} completed",
            events=[{"evidenceId": f"evidence-{agent_id}"}],
            changed_files=[f"src/{agent_id}.js"],
            test_commands=[f"pytest tests/{agent_id}"],
            error=None,
        )


def _completed_result(client, accepted):
    # Project generation includes release evidence and filesystem checks;
    # allow normal Windows CI/desktop load without treating a slow worker as
    # a product failure.
    deadline = time.monotonic() + 30
    job = None
    while time.monotonic() < deadline:
        job = client.get(f"/api/assistant/jobs/{accepted['jobId']}").json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.02)
    assert job and job["status"] == "completed", job
    return job["result"]


def test_user_can_request_todo_and_receive_a_generated_project(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    with TestClient(create_app(settings, agent_runtime=FakeAgentRuntime())) as client:
        response = client.post("/api/assistant/route", json={"text": "Todo 앱 만들어줘"})

        assert response.status_code == 200, response.text
        accepted = response.json()
        assert accepted["status"] == "accepted", accepted
        payload = _completed_result(client, accepted)
    assert payload["project_profile"], payload
    workspace = Path(payload["project_profile"]["workspace"])
    assert payload["selection"]["capability_id"] == "project-execution"
    # A generated project can have a PASS quality run while the release
    # review still blocks completion on missing rollback evidence.
    assert payload["status"] == "blocked", payload
    assert payload["quality_status"] == "PASS", payload
    assert payload["qa_report_path"].endswith("QA_REPORT.json")
    assert payload["release_manifest_path"].endswith("RELEASE_MANIFEST.json")
    assert payload["response_verification"]["profile_version"] == "claimlatch-v0.2.0"
    assert payload["git_branch"].startswith("project/")
    assert len(payload["git_commit"]) == 40
    assert payload["execution_plan_path"].endswith("execution-plan.json")
    assert (workspace / "index.html").is_file()
    assert (workspace / "src" / "entities" / "todo" / "model.js").is_file()
    assert (workspace / "README.md").is_file()
    assert (workspace / "execution-plan.json").is_file()
    assert (workspace / "PROJECT_PROFILE.json").is_file()
    assert (workspace / "PROJECT_LOG.md").is_file()


def test_user_can_request_a_login_web_todo_and_receive_a_full_stack_project(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    with TestClient(create_app(settings, agent_runtime=FakeAgentRuntime())) as client:
        response = client.post("/api/assistant/route", json={"text": "로그인 기능이 있는 Todo 웹앱 만들어줘"})

        payload = _completed_result(client, response.json())
        workspace = Path(payload["project_profile"]["workspace"])
        assert response.status_code == 200, response.text
        assert payload["project_profile"]["runtime_profile"] == "web_app"
        assert payload["quality_status"] == "PASS", payload
        assert (workspace / "apps" / "web" / "index.html").is_file()
        assert (workspace / "apps" / "api" / "server.py").is_file()
        assert any(item["state"] == "awaiting_configuration" for item in payload["project_profile"]["connectors"])
