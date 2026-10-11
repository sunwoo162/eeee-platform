import json
from pathlib import Path

from app.kernel.capabilities import _persist_agent_execution_report


def test_agent_execution_report_is_persisted_in_plan_and_project_log(tmp_path: Path) -> None:
    plan = tmp_path / "execution-plan.json"
    plan.write_text(json.dumps({"schemaVersion": 1}, ensure_ascii=False), encoding="utf-8")
    log = tmp_path / "PROJECT_LOG.md"
    log.write_text("# Project Log\n", encoding="utf-8")

    report = {
        "graphVersion": "iseol-agent-graph.v1",
        "status": "completed",
        "agents": [
            {
                "agentId": "requirements",
                "status": "passed",
                "summary": "requirements evidence",
                "reason": "ClaimLatch verified the action",
                "evidenceIds": ["local-evidence-1"],
                "changedFiles": ["docs/requirements.md"],
                "claimLatchDecision": "PASS",
            }
        ],
    }

    _persist_agent_execution_report(plan, log, report)

    saved_plan = json.loads(plan.read_text(encoding="utf-8"))
    assert saved_plan["agentExecutionReport"] == report
    saved_log = log.read_text(encoding="utf-8")
    assert "## ISEOL specialist execution" in saved_log
    assert "requirements: passed" in saved_log
    assert "local-evidence-1" in saved_log
