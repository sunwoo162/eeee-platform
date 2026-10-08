from datetime import datetime, timedelta, timezone

from app.contracts import ExecutionEnvelope, ExecutionStatus
from app.project_view.service import ProjectViewService
from app.runtime.store import ExecutionStore
from app.storage.sqlite import SQLiteStore


def test_project_map_renders_real_agent_graph_and_handoff_status(tmp_path):
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    store.create_project("p", "Todo", str(tmp_path), revision="r1")
    envelope = ExecutionEnvelope(
        execution_id="execution-1", request_id="request-1", project_id="p",
        project_revision="r1", capability_id="project-execution", tool_id="iseol",
        actor="ISEOL", status=ExecutionStatus.COMPLETED,
        evidence_ids=("evidence-frontend",),
        started_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        completed_at=datetime.now(timezone.utc),
        output={
            "agentGraph": {"schemaVersion": "iseol-agent-graph.v1", "agents": [
                {"id": "requirements", "taskId": "requirements", "role": "requirements", "title": "Requirements Agent", "goal": "requirements", "dependencies": []},
                {"id": "frontend", "taskId": "frontend", "role": "frontend", "title": "Frontend Agent", "goal": "frontend", "dependencies": ["requirements"]},
            ]},
            "agentExecutionReport": {"graphVersion": "iseol-agent-graph.v1", "status": "blocked", "agents": [
                {"agentId": "requirements", "taskId": "requirements", "role": "requirements", "status": "passed", "summary": "done", "changedFiles": [], "evidenceIds": [], "claimLatchDecision": "PASS", "reason": "verified", "startedAt": "2026-10-07T00:00:00Z", "completedAt": "2026-10-07T00:00:01Z"},
                {"agentId": "frontend", "taskId": "frontend", "role": "frontend", "status": "blocked", "summary": "blocked", "changedFiles": ["src/ui.tsx"], "evidenceIds": ["evidence-frontend"], "claimLatchDecision": "BLOCKED", "reason": "missing evidence", "startedAt": "2026-10-07T00:00:00Z", "completedAt": "2026-10-07T00:00:01Z"},
            ]},
        },
    )
    ExecutionStore(store).save(envelope)

    result = ProjectViewService(store).get_snapshot("p")

    nodes = {node.id: node for node in result.nodes}
    assert nodes["agent:requirements"].status == "completed"
    assert nodes["agent:frontend"].status == "blocked"
    assert nodes["agent:frontend"].claim_latch_status == "BLOCK"
    assert nodes["agent:frontend"].changed_files == ["src/ui.tsx"]
    assert any(edge.source == "agent:requirements" and edge.target == "agent:frontend" and edge.kind == "dependency" for edge in result.edges)
