import json
from pathlib import Path

from app.portfolio.service import PortfolioGenerator


def test_generator_writes_portfolio_artifacts_with_source_evidence(tmp_path: Path) -> None:
    (tmp_path / "PROJECT_PROFILE.json").write_text(
        json.dumps({"projectId": "project-1", "goal": "Todo 앱", "runtimeProfile": "web_app"}),
        encoding="utf-8",
    )
    (tmp_path / "PROJECT_LOG.md").write_text(
        "# Project Log\n\n## Troubleshooting\n- Windows DLL 로딩 문제를 환경 점검으로 해결\n",
        encoding="utf-8",
    )
    (tmp_path / "QA_REPORT.json").write_text(
        json.dumps({"status": "PASS", "claimLatch": {"decision": "PASS"}}), encoding="utf-8"
    )
    (tmp_path / "RELEASE_MANIFEST.json").write_text(
        json.dumps({"status": "released", "artifacts": ["dist"]}), encoding="utf-8"
    )

    result = PortfolioGenerator().generate("project-1", "rev-1", tmp_path)

    assert result.status == "completed"
    assert {"PORTFOLIO.md", "TECHNICAL_RETROSPECTIVE.md", "RESUME_SUMMARY.md", "INTERVIEW_ANSWERS.md"} <= {
        Path(item["path"]).name for item in result.artifacts
    }
    portfolio = (tmp_path / "PORTFOLIO.md").read_text(encoding="utf-8")
    assert "PROJECT_LOG.md" in portfolio
    assert "QA_REPORT.json" in portfolio
    assert "ClaimLatch" in portfolio
    assert "Windows DLL 로딩 문제" in portfolio


def test_generator_blocks_when_project_evidence_is_missing(tmp_path: Path) -> None:
    result = PortfolioGenerator().generate("project-1", "rev-1", tmp_path)

    assert result.status == "blocked"
    assert result.artifacts == []
    assert "PROJECT_PROFILE.json" in result.message
