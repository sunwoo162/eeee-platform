from app.iseol.quality import ProductQualityProfile


def test_portfolio_quality_profile_requires_product_evidence() -> None:
    profile = ProductQualityProfile.portfolio_grade()

    assert profile.id == "portfolio-grade-v1"
    assert {
        "requirements",
        "design-system",
        "architecture",
        "implementation",
        "test-suite",
        "responsive-accessibility",
        "security",
        "troubleshooting",
        "runbook",
        "release-evidence",
    } <= {artifact.id for artifact in profile.artifacts}


def test_portfolio_quality_profile_blocks_missing_release_evidence(tmp_path) -> None:
    profile = ProductQualityProfile.portfolio_grade()

    report = profile.evaluate(tmp_path)

    assert report.decision == "BLOCK"
    assert {check.name for check in report.checks} >= {
        "quality:requirements",
        "quality:release-evidence",
    }


def test_portfolio_quality_profile_passes_generated_todo_artifacts(tmp_path) -> None:
    from app.project_runtime.scaffold import create_todo_scaffold

    create_todo_scaffold(tmp_path)
    (tmp_path / "QA_REPORT.json").write_text("{}\n", encoding="utf-8")
    report = ProductQualityProfile.portfolio_grade().evaluate(tmp_path, require_release_evidence=False)

    assert report.decision == "PASS", report
    assert all(check.status == "PASS" for check in report.checks)
