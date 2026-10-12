from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReleaseArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    evidence_project_id: str | None = None
    evidence_project_revision: str | None = None


class ReleaseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    decision: str
    project_id: str = Field(min_length=1)
    project_revision: str = Field(min_length=1)
    workspace: str = Field(min_length=1)
    artifact_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    claim_latch_receipt_id: str = Field(min_length=1)
    claim_latch_report_id: str = Field(min_length=1)
    created_at: datetime


def build_release_manifest(
    *,
    project_id: str,
    project_revision: str,
    workspace: str,
    artifacts: list[dict[str, Any]],
    qa_report: dict[str, Any],
    claim_latch: dict[str, Any],
) -> ReleaseManifest:
    reasons: list[str] = []
    if qa_report.get("projectId") != project_id or qa_report.get("projectRevision") != project_revision:
        reasons.append("QA report is stale")
    if qa_report.get("status") != "PASS" or qa_report.get("independent") is not True:
        reasons.append("independent QA did not PASS")
    qa_evidence = [item for item in qa_report.get("evidenceIds", []) if isinstance(item, str) and item]
    if not qa_evidence:
        reasons.append("QA evidence is missing")
    if claim_latch.get("decision") != "PASS" or not claim_latch.get("receiptId"):
        reasons.append("ClaimLatch release verification did not PASS")
    try:
        parsed_artifacts = [ReleaseArtifact.model_validate(item) for item in artifacts]
    except Exception as exc:
        raise ValueError("release blocked: invalid artifact evidence") from exc
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        reasons.append("workspace does not exist")
    for artifact in parsed_artifacts:
        artifact_path = (root / artifact.path).resolve()
        try:
            artifact_path.relative_to(root)
        except ValueError:
            reasons.append(f"artifact path outside workspace: {artifact.path}")
            continue
        if not artifact_path.exists():
            reasons.append(f"artifact path does not exist: {artifact.path}")
            continue
        if artifact.evidence_project_id or artifact.evidence_project_revision:
            if (
                artifact.evidence_project_id != project_id
                or artifact.evidence_project_revision != project_revision
            ):
                reasons.append(f"artifact evidence is stale: {artifact.id}")
        for file_path in _text_files(artifact_path):
            try:
                file_path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                reasons.append(f"artifact is not valid UTF-8: {file_path.relative_to(root)}")
    evidence_ids = list(dict.fromkeys([*(evidence for artifact in parsed_artifacts for evidence in artifact.evidence_ids), *qa_evidence]))
    if reasons:
        raise ValueError("release blocked: " + "; ".join(reasons))
    return ReleaseManifest(
        decision="PASS",
        project_id=project_id,
        project_revision=project_revision,
        workspace=workspace,
        artifact_ids=[artifact.id for artifact in parsed_artifacts],
        evidence_ids=evidence_ids,
        claim_latch_receipt_id=str(claim_latch["receiptId"]),
        claim_latch_report_id=str(claim_latch["claimLatchReportId"]),
        created_at=datetime.now(timezone.utc),
    )


_BINARY_SUFFIXES = {
    ".7z", ".avi", ".bmp", ".class", ".dll", ".exe", ".gif", ".ico", ".jpeg", ".jpg",
    ".mov", ".mp3", ".mp4", ".otf", ".pdf", ".png", ".so", ".tar", ".ttf", ".wav", ".webp",
    ".pyc", ".pyo", ".woff", ".woff2", ".zip",
}


def _text_files(path: Path) -> list[Path]:
    if path.is_file():
        return [] if path.suffix.lower() in _BINARY_SUFFIXES else [path]
    return [
        child
        for child in path.rglob("*")
        if child.is_file() and child.suffix.lower() not in _BINARY_SUFFIXES
    ]
