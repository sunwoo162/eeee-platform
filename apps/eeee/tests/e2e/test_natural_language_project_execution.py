import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.protocol import AgentResult
from app.config import Settings
from app.main import create_app


class PassingAgentRuntime:
    def run(self, request):
        agent_id = request.prompt.split("agentId=")[1].split()[0]
        return AgentResult(
            status="completed",
            summary=f"{agent_id} evidence recorded",
            events=[{"evidenceId": f"evidence-{agent_id}"}],
            changed_files=["README.md"],
            test_commands=["python -m pytest -q"],
            error=None,
        )


class FailingAgentRuntime:
    def run(self, request):
        return AgentResult(
            status="failed",
            summary="specialist runtime unavailable",
            events=[],
            changed_files=[],
            test_commands=[],
            error="specialist runtime unavailable",
        )


def _wait_for_job(client: TestClient, accepted: dict[str, object], *, timeout: float = 60.0) -> dict[str, object]:
    assert accepted["status"] == "accepted", accepted
    job_id = accepted["jobId"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/assistant/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed"}:
            assert job["status"] == "completed", job
            assert isinstance(job["result"], dict), job
            return job["result"]
        time.sleep(0.02)
    raise AssertionError(f"background job did not finish: {job_id}")


def _client(tmp_path: Path, runtime) -> TestClient:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    return TestClient(create_app(settings, agent_runtime=runtime))


def test_one_sentence_meal_web_request_produces_local_verified_project(tmp_path) -> None:
    client = _client(tmp_path, PassingAgentRuntime())

    accepted = client.post(
        "/api/assistant/route",
        json={"text": "오늘 식단을 정리해주는 웹 만들어줘"},
    ).json()
    result = _wait_for_job(client, accepted)
    project_id = result["project_id"]

    assert result["template_id"] == "meal_planner"
    assert result["quality_status"] == "PASS"
    assert result["final_report_path"].endswith("FINAL-QUALITY-REPORT.json")
    assert result["quality_grade"] == "client_ready_with_notes"
    assert Path(result["final_report_path"]).is_file()
    quality = client.get(f"/api/projects/{project_id}/quality").json()
    assert quality["projectId"] == project_id
    assert quality["grade"] == result["quality_grade"]
    assert quality["limitations"]


def test_natural_language_request_does_not_load_unrelated_plugins(tmp_path) -> None:
    client = _client(tmp_path, PassingAgentRuntime())
    accepted = client.post("/api/assistant/route", json={"text": "오늘 식단을 정리해주는 웹 만들어줘"}).json()
    result = _wait_for_job(client, accepted)

    plan = client.get(f"/api/projects/{result['project_id']}/execution-plan").json()
    serialized = str(plan).casefold()
    assert "gmail" not in serialized
    assert "github" not in serialized
    assert "figma" not in serialized
    assert "notion" not in serialized
    assert plan["selectedExtensions"] == ["meal-planner"]


def test_restart_resumes_same_project_and_keeps_final_report(tmp_path) -> None:
    first = _client(tmp_path, PassingAgentRuntime())
    accepted = first.post("/api/assistant/route", json={"text": "오늘 식단을 정리해주는 웹 만들어줘"}).json()
    result = _wait_for_job(first, accepted)
    project_id = result["project_id"]

    restarted = _client(tmp_path, PassingAgentRuntime())
    quality = restarted.get(f"/api/projects/{project_id}/quality")
    plan = restarted.get(f"/api/projects/{project_id}/execution-plan")

    assert quality.status_code == 200
    assert quality.json()["projectId"] == project_id
    assert plan.status_code == 200
    assert plan.json()["projectId"] == project_id


def test_failed_agent_produces_blocked_quality_report(tmp_path) -> None:
    client = _client(tmp_path, FailingAgentRuntime())
    accepted = client.post("/api/assistant/route", json={"text": "오늘 식단을 정리해주는 웹 만들어줘"}).json()
    result = _wait_for_job(client, accepted)

    assert result["status"] == "blocked"
    assert result["final_report_path"].endswith("FINAL-QUALITY-REPORT.json")
    assert result["quality_grade"] == "replan_required"
    assert result["final_blockers"]
    quality = client.get(f"/api/projects/{result['project_id']}/quality").json()
    assert quality["grade"] == "replan_required"
    assert quality["blockers"]
