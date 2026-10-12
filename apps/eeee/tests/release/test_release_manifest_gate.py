import pytest

from app.release.manifest import build_release_manifest


def _artifact(
    artifact_id: str,
    path: str,
    evidence_ids: list[str],
    *,
    project_id: str = "project-1",
    revision: str = "rev-1",
) -> dict[str, object]:
    return {
        "id": artifact_id,
        "path": path,
        "evidence_ids": evidence_ids,
        "evidence_project_id": project_id,
        "evidence_project_revision": revision,
    }


def _input(**overrides):
    value = {
        "project_id": "project-1",
        "project_revision": "rev-1",
        "workspace": "C:/workspace/project-1",
        "artifacts": [
            _artifact("source", "src", ["evidence-source"]),
            _artifact("qa", "QA_REPORT.md", ["evidence-qa"]),
        ],
        "qa_report": {
            "projectId": "project-1",
            "projectRevision": "rev-1",
            "status": "PASS",
            "independent": True,
            "evidenceIds": ["evidence-qa"],
        },
        "claim_latch": {
            "decision": "PASS",
            "receiptId": "receipt-1",
            "claimLatchReportId": "report-1",
        },
    }
    value.update(overrides)
    return value


def test_release_manifest_passes_only_with_current_qa_claimlatch_and_artifacts(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "QA_REPORT.md").write_text("qa", encoding="utf-8")
    manifest = build_release_manifest(
        **_input(
            workspace=str(tmp_path),
            artifacts=[
                _artifact("source", "src", ["evidence-source"]),
                _artifact("qa", "QA_REPORT.md", ["evidence-qa"]),
            ],
        )
    )
    assert manifest.decision == "PASS"
    assert manifest.project_id == "project-1"
    assert manifest.claim_latch_receipt_id == "receipt-1"
    assert manifest.evidence_ids == ["evidence-source", "evidence-qa"]


def test_release_manifest_blocks_stale_or_unverified_results(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "QA_REPORT.md").write_text("qa", encoding="utf-8")
    values = _input(
        workspace=str(tmp_path),
        artifacts=[
            _artifact("source", "src", ["evidence-source"]),
            _artifact("qa", "QA_REPORT.md", ["evidence-qa"]),
        ],
    )
    with pytest.raises(ValueError, match="release blocked"):
        build_release_manifest(
            **dict(
                values,
                qa_report={
                    "projectId": "project-1",
                    "projectRevision": "old-rev",
                    "status": "PASS",
                    "independent": True,
                    "evidenceIds": ["evidence-qa"],
                }
            )
        )
    with pytest.raises(ValueError, match="release blocked"):
        build_release_manifest(**dict(values, claim_latch={"decision": "WARN", "receiptId": None, "claimLatchReportId": "report-1"}))


def test_release_manifest_blocks_artifact_without_evidence() -> None:
    with pytest.raises(ValueError, match="release blocked"):
        build_release_manifest(**_input(artifacts=[_artifact("source", "src", [])]))


def test_release_manifest_blocks_whitespace_only_qa_evidence() -> None:
    values = _input()
    values["qa_report"] = {
        **values["qa_report"],
        "evidenceIds": ["   "],
    }

    with pytest.raises(ValueError, match="QA evidence is missing"):
        build_release_manifest(**values)


def test_release_manifest_blocks_non_list_qa_evidence() -> None:
    values = _input()
    values["qa_report"] = {
        **values["qa_report"],
        "evidenceIds": "evidence-string",
    }

    with pytest.raises(ValueError, match="QA evidence contains invalid values"):
        build_release_manifest(**values)


def test_release_manifest_blocks_claimlatch_without_report_id() -> None:
    values = _input()
    values["claim_latch"] = {
        "decision": "PASS",
        "receiptId": "receipt-1",
    }

    with pytest.raises(ValueError, match="ClaimLatch release verification did not PASS"):
        build_release_manifest(**values)


def test_release_manifest_blocks_missing_artifact_path(tmp_path) -> None:
    with pytest.raises(ValueError, match="artifact path does not exist"):
        build_release_manifest(**_input(workspace=str(tmp_path)))


def test_release_manifest_blocks_artifact_path_escape(tmp_path) -> None:
    (tmp_path / "QA_REPORT.md").write_text("qa", encoding="utf-8")
    with pytest.raises(ValueError, match="outside workspace"):
        build_release_manifest(
            **_input(
                workspace=str(tmp_path),
                artifacts=[
                    _artifact("escape", "../outside.txt", ["evidence-source"]),
                    _artifact("qa", "QA_REPORT.md", ["evidence-qa"]),
                ],
            )
        )


def test_release_manifest_blocks_invalid_utf8_text_artifact(tmp_path) -> None:
    (tmp_path / "QA_REPORT.md").write_text("qa", encoding="utf-8")
    (tmp_path / "broken.txt").write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="not valid UTF-8"):
        build_release_manifest(
            **_input(
                workspace=str(tmp_path),
                artifacts=[
                    _artifact("broken", "broken.txt", ["evidence-source"]),
                    _artifact("qa", "QA_REPORT.md", ["evidence-qa"]),
                ],
            )
        )


def test_release_manifest_blocks_artifact_evidence_from_stale_revision(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "QA_REPORT.md").write_text("qa", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact evidence is stale"):
        build_release_manifest(
            **_input(
                workspace=str(tmp_path),
                artifacts=[
                    {
                        "id": "source",
                        "path": "src",
                        "evidence_ids": ["evidence-source"],
                        "evidence_project_id": "project-1",
                        "evidence_project_revision": "old-rev",
                    },
                    _artifact("qa", "QA_REPORT.md", ["evidence-qa"]),
                ],
            )
        )
