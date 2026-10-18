import json

from app.iseol.contracts import ProjectExecutionPlan, ProjectIntent
from app.iseol.quality import inspect_text_integrity
from app.iseol.review import ProjectQualityEvaluator


def _intent() -> ProjectIntent:
    return ProjectIntent(
        rawText="카페 홈페이지 웹 만들어줘",
        goal="카페 홈페이지",
        projectType="web_app",
        templateId="generic_web",
        assumptions=["local-first"],
        acceptanceCriteria=["핵심 화면이 실행됨"],
    )


def _plan() -> ProjectExecutionPlan:
    intent = _intent()
    return ProjectExecutionPlan(
        projectId="project-1",
        projectRevision="rev-1",
        requestId="request-1",
        intent=intent,
        phases=["requirements", "ui", "implementation", "testing", "release"],
        tasks=[{"id": "frontend", "status": "passed"}],
    )


def _workspace(root) -> None:
    files = {
        "README.md": "# 카페 홈페이지\n실행 방법과 요구사항\n",
        "DESIGN.md": "# 디자인 시스템\n반응형 UX UI\n",
        "PROJECT_LOG.md": "# 작업 기록\n보안·트러블슈팅\n",
        "DEPLOYMENT.md": "# 운영\nrollback: 이전 릴리스로 복구\n",
        "index.html": '<meta name="viewport" content="width=device-width">\n',
        "src/app.js": "export const app = true;\n",
        "tests/e2e.md": "# E2E\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _qa() -> dict[str, object]:
    return {
        "id": "qa-1",
        "projectId": "project-1",
        "projectRevision": "rev-1",
        "status": "PASS",
        "independent": True,
        "evidenceIds": ["qa-evidence-1"],
        "checks": [{"name": "e2e", "status": "passed"}],
    }


def test_final_report_scores_required_categories(tmp_path) -> None:
    _workspace(tmp_path)

    report = ProjectQualityEvaluator().evaluate(
        tmp_path, _intent(), _plan(), _qa(),
        {"decision": "PASS", "receiptId": "receipt-1", "claimLatchReportId": "report-1"},
    )

    assert sum(category.max_points for category in report.categories) == 100
    assert {category.id for category in report.categories} == {
        "requirements", "research-content-ia", "ux-ui-design", "technical-code",
        "tests-security-accessibility-performance", "deploy-ops-recovery", "docs-handoff-portfolio",
    }
    assert report.score > 0
    assert (tmp_path / "FINAL-QUALITY-REPORT.json").is_file()
    assert json.loads((tmp_path / "FINAL-QUALITY-REPORT.json").read_text(encoding="utf-8"))["score"] == report.score


def test_final_report_blocks_false_completion(tmp_path) -> None:
    _workspace(tmp_path)

    report = ProjectQualityEvaluator().evaluate(
        tmp_path, _intent(), _plan(), _qa(),
        {"decision": "BLOCKED", "receiptId": None, "claimLatchReportId": None},
    )

    assert report.grade in {"revision_required", "replan_required"}
    assert any("ClaimLatch" in blocker for blocker in report.blockers)


def test_quality_checks_replacement_characters_bom_and_diff_whitespace(tmp_path) -> None:
    (tmp_path / "bad.txt").write_bytes(b"\xef\xbb\xbf" + "bad\ufffd\n".encode("utf-8"))

    checks = inspect_text_integrity(tmp_path)

    assert any(check.name == "encoding:bom" and check.status == "BLOCK" for check in checks)
    assert any(check.name == "encoding:replacement-character" and check.status == "BLOCK" for check in checks)
    assert any(check.name == "git:diff-check" for check in checks)


def test_quality_report_records_missing_plugin_as_limitation_not_success(tmp_path) -> None:
    _workspace(tmp_path)
    plan = _plan().model_copy(update={"missing_extensions": ["connector.figma.read"]})

    report = ProjectQualityEvaluator().evaluate(
        tmp_path, _intent(), plan, _qa(),
        {"decision": "PASS", "receiptId": "receipt-1", "claimLatchReportId": "report-1"},
    )

    assert any("connector.figma.read" in limitation for limitation in report.limitations)
    assert report.grade != "portfolio_ready"
