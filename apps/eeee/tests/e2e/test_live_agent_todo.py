from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.agent.protocol import AgentResult
from app.config import Settings
from app.main import create_app


class FakeAgentRuntime:
    def run(self, request):
        agent_id = request.prompt.split("agentId=")[1].split()[0]
        return AgentResult(
            status="completed",
            summary=f"{agent_id} completed",
            events=[{"evidenceId": f"evidence-{agent_id}"}],
            changed_files=[f"src/{agent_id}.js"],
            test_commands=[f"pytest tests/{agent_id}"],
            error=None,
        )


class FakeClaimLatchClient:
    def require_pass(self, payload):
        return SimpleNamespace(
            decision="PASS",
            subject_id=payload["subjectId"],
            project_id=payload["projectId"],
            project_revision=payload["projectRevision"],
            claim_latch_report_id=f"report-{payload['subjectId']}",
            receipt_id=f"receipt-{payload['subjectId']}",
        )

    def verify_structured(self, payload):
        return {
            "decision": "PASS",
            "subjectId": payload["subjectId"],
            "projectId": payload["projectId"],
            "projectRevision": payload["projectRevision"],
            "claimLatchReportId": f"report-{payload['subjectId']}",
            "receiptId": f"receipt-{payload['subjectId']}",
        }


def test_user_todo_request_executes_specialist_graph_and_renders_it(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
        llm_api_key="test-key",
        claim_latch_auto_start=False,
        claim_latch_mode="required",
    )
    application = create_app(settings, agent_runtime=FakeAgentRuntime())
    application.state.trust_gate.client = FakeClaimLatchClient()

    with TestClient(application) as client:
        response = client.post("/api/assistant/route", json={"text": "Todo 앱 만들어줘"})

        assert response.status_code == 200, response.text
        payload = response.json()
        project_id = payload["project_id"]
        assert payload["project_profile"], payload
        workspace = Path(payload["project_profile"]["workspace"])
        assert (workspace / "src" / "entities" / "todo" / "model.js").is_file()

        project_map = client.get(f"/api/projects/{project_id}/map")
        assert project_map.status_code == 200
        agents = {
            node["id"]: node
            for node in project_map.json()["nodes"]
            if node["id"].startswith("agent:")
        }
        assert len(agents) == 13
        assert all(node["status"] == "completed" for node in agents.values())
        assert all(node["claimLatchStatus"] == "PASS" for node in agents.values())
