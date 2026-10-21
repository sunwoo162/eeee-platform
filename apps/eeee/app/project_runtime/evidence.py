from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone

from app.domain.errors import ApprovalError
from app.integrations.contracts import GithubReviewResultV1
from app.project_runtime.models import ProjectEvidenceIngestionResult, ProjectEvidenceRecord
from app.storage.sqlite import SQLiteStore


class ProjectEvidenceService:
    """Ingest verified ISEOL evidence into the Desktop-owned project ledger."""

    def __init__(
        self,
        store: SQLiteStore,
        trust_gate: object,
        event_publisher: Callable[[str, dict[str, object]], object] | None = None,
    ) -> None:
        self.store = store
        self.trust_gate = trust_gate
        self.event_publisher = event_publisher

    def ingest_github_review(
        self, result: GithubReviewResultV1, *, user_id: str = "local-user"
    ) -> ProjectEvidenceIngestionResult:
        project = self.store.get_project(result.project_id, user_id=user_id)
        if project.revision != result.project_revision:
            raise ApprovalError(
                "Cannot ingest GitHub review evidence: stale project revision "
                f"{result.project_revision}; current is {project.revision}"
            )

        reference = f"github:{result.repository}:pr:{result.pull_number}:{result.head_sha}"
        content_hash = _content_hash(result.model_dump(mode="json", by_alias=True))
        try:
            existing = self.store.get_project_evidence(
                result.project_id, "github-review", result.head_sha
            )
        except KeyError:
            existing = None
        if existing is not None and existing.content_hash == content_hash:
            return ProjectEvidenceIngestionResult(status="duplicate", evidence=existing)

        trust = self.trust_gate.verify_action(
            subject_id=reference,
            project_id=result.project_id,
            project_revision=result.project_revision,
            action="project.evidence.github_review.ingest",
            payload={
                "repository": result.repository,
                "pullNumber": result.pull_number,
                "headSha": result.head_sha,
                "reviewStatus": result.review_status,
                "findingsCount": result.findings_count,
            },
        )
        if trust.decision == "BLOCKED":
            self._publish(
                "project.evidence.blocked",
                {
                    "projectId": result.project_id,
                    "projectRevision": result.project_revision,
                    "evidenceType": "github-review",
                    "headSha": result.head_sha,
                    "reason": trust.reason,
                },
                user_id=user_id,
            )
            return ProjectEvidenceIngestionResult(
                status="blocked", trust=trust, reason=trust.reason
            )

        evidence = ProjectEvidenceRecord(
            project_id=result.project_id,
            evidence_type="github-review",
            project_revision=result.project_revision,
            reference=reference,
            content_hash=content_hash,
            payload=result.model_dump(mode="json", by_alias=True),
            created_at=datetime.now(timezone.utc),
        )
        self.store.save_project_evidence(evidence)
        self._publish(
            "project.evidence.accepted",
            {
                "projectId": result.project_id,
                "projectRevision": result.project_revision,
                "evidenceType": "github-review",
                "repository": result.repository,
                "pullNumber": result.pull_number,
                "headSha": result.head_sha,
                "reviewStatus": result.review_status,
                "findingsCount": result.findings_count,
                "trustDecision": trust.decision,
            },
            user_id=user_id,
        )
        return ProjectEvidenceIngestionResult(status="accepted", evidence=evidence, trust=trust)

    def _publish(
        self, kind: str, payload: dict[str, object], *, user_id: str = "local-user"
    ) -> None:
        if self.event_publisher is not None:
            self.event_publisher(kind, {**payload, "userId": user_id})


def _content_hash(value: dict[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
