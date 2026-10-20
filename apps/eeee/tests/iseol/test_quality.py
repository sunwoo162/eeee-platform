from pathlib import Path

from app.agent.protocol import AgentResult
from app.iseol.agents import AgentNode
from app.iseol.quality import QualityGate


def test_quality_gate_blocks_secret_and_invalid_encoding(tmp_path):
    secret_file = tmp_path / "src.py"
    secret_file.write_text('API_KEY = "super-secret-token-value"\n', encoding="utf-8")
    bad_file = tmp_path / "bad.txt"
    bad_file.write_bytes(b"\xff\xfe")
    node = AgentNode(id="review", taskId="review", role="review", title="Review", goal="review", acceptanceCriteria=[])
    result = AgentResult("completed", "reviewed", [{"evidenceId": "ev"}], ["src.py", "bad.txt"], ["pytest tests"], None)

    report = QualityGate(tmp_path).evaluate(node, result)

    assert report.decision == "BLOCK"
    assert any("secret" in check.message.lower() for check in report.checks)
    assert any("utf-8" in check.message.lower() for check in report.checks)


def test_quality_gate_passes_frontend_with_viewport_and_clean_files(tmp_path):
    (tmp_path / "index.html").write_text(
        '<meta name="viewport" content="width=device-width, initial-scale=1">', encoding="utf-8"
    )
    (tmp_path / "src.js").write_text("export const ok = true;\n", encoding="utf-8")
    node = AgentNode(id="frontend", taskId="frontend", role="frontend", title="Frontend", goal="ui", acceptanceCriteria=[])
    result = AgentResult("completed", "ui done", [{"evidenceId": "ev"}], ["index.html", "src.js"], ["npm test"], None)

    report = QualityGate(tmp_path).evaluate(node, result)

    assert report.decision == "PASS"
    assert all(check.status == "PASS" for check in report.checks)


def test_quality_gate_blocks_a_completed_agent_without_changed_files(tmp_path):
    node = AgentNode(id="requirements", taskId="requirements", role="requirements", title="Requirements", goal="requirements", acceptanceCriteria=[])
    result = AgentResult("completed", "requirements done", [{"evidenceId": "ev"}], [], ["pytest tests"], None)

    report = QualityGate(tmp_path).evaluate(node, result)

    assert report.decision == "BLOCK"
    assert any(check.name == "changed-files" and check.status == "BLOCK" for check in report.checks)
