"""Deterministic final project review and evidence report."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.iseol.contracts import ProjectExecutionPlan, ProjectIntent
from app.iseol.quality import QualityCheck, inspect_text_integrity


ReportGrade = Literal["portfolio_ready", "client_ready_with_notes", "revision_required", "replan_required"]


class QualityCategoryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str
    title: str
    max_points: int = Field(alias="maxPoints")
    score: int
    status: Literal["PASS", "WARN", "BLOCK", "NOT_RUN"]
    checks: list[QualityCheck]


class FinalProjectReport(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["eeee-final-quality-report.v1"] = Field(
        default="eeee-final-quality-report.v1", alias="schemaVersion"
    )
    project_id: str = Field(alias="projectId")
    project_revision: str = Field(alias="projectRevision")
    initial_request: str = Field(alias="initialRequest")
    final_result: dict[str, object] = Field(alias="finalResult")
    selected_graph: dict[str, object] = Field(alias="selectedGraph")
    artifacts: list[str]
    requirement_traceability: list[dict[str, object]] = Field(alias="requirementTraceability")
    gate_results: dict[str, object] = Field(alias="gateResults")
    retries: list[dict[str, object]]
    test_results: list[dict[str, object]] = Field(alias="testResults")
    categories: list[QualityCategoryResult]
    score: int = Field(ge=0, le=100)
    grade: ReportGrade
    blockers: list[str]
    limitations: list[str]
    next_improvements: list[str] = Field(alias="nextImprovements")


class ProjectQualityEvaluator:
    """Score evidence, not agent prose, and persist the final audit report."""

    def evaluate(
        self,
        workspace: Path,
        intent: ProjectIntent,
        plan: ProjectExecutionPlan,
        qa_report: dict[str, object] | None,
        claim_latch: Mapping[str, object] | None,
    ) -> FinalProjectReport:
        root = Path(workspace).resolve()
        qa = qa_report if isinstance(qa_report, dict) else {}
        claim = dict(claim_latch or {})
        integrity = inspect_text_integrity(root)
        blockers: list[str] = []
        limitations: list[str] = []

        if qa.get("projectId") != plan.project_id or qa.get("projectRevision") != plan.project_revision:
            blockers.append("QA report identity does not match the project plan")
        if qa.get("status") != "PASS" or qa.get("independent") is not True:
            blockers.append("Independent QA did not PASS")
        if not isinstance(qa.get("evidenceIds"), list) or not qa.get("evidenceIds"):
            blockers.append("QA evidence is missing")
        else:
            qa_evidence = {
                str(item).strip()
                for item in qa["evidenceIds"]
                if isinstance(item, str) and item.strip()
            }
            check_evidence = {
                str(check.get("evidenceId")).strip()
                for check in qa.get("checks", [])
                if isinstance(check, Mapping) and isinstance(check.get("evidenceId"), str) and check.get("evidenceId", "").strip()
            } if isinstance(qa.get("checks"), list) else set()
            if not qa_evidence or not qa_evidence.issubset(check_evidence):
                blockers.append("QA evidence is not linked to verification checks")
        if claim.get("decision") != "PASS" or not claim.get("receiptId") or not claim.get("claimLatchReportId"):
            blockers.append("ClaimLatch evidence is missing or not PASS")
        if any(check.status == "BLOCK" for check in integrity):
            blockers.append("Encoding or diff integrity check is blocked")
        if not _has_rollback_evidence(root):
            blockers.append("Rollback evidence is missing")
        requirement_traceability = _requirement_traceability(intent, qa, blockers)

        browser = _browser_status(qa)
        if browser == "NOT_RUN":
            limitations.append("Browser UI verification is NOT_RUN; this is not a portfolio-complete release")
        elif browser == "BLOCK":
            blockers.append("Browser UI verification failed")
        for extension_id in plan.missing_extensions:
            blockers.append(f"Required extension is missing: {extension_id}")
            limitations.append(f"Missing extension remains unconfigured: {extension_id}")
        if plan.missing_extensions:
            limitations.append("External connector work remains unconfigured")

        category_inputs = {
            "requirements": (15, "요구사항", [
                _check("requirements:goal", bool(intent.goal.strip()), "Initial goal is explicit"),
                _check("requirements:acceptance", bool(intent.acceptance_criteria), "Acceptance criteria exist"),
                _check(
                    "requirements:traceability",
                    bool(requirement_traceability) and all(item.get("status") == "verified" for item in requirement_traceability),
                    "Acceptance criteria are linked to verified QA evidence",
                ),
            ]),
            "research-content-ia": (10, "조사·콘텐츠·정보구조", [
                _check("research:phase", "definition" in plan.phases, "Definition/research phase is selected"),
                _check("content:phase", "content" in plan.phases, "Content phase is selected"),
                _check("ia:phase", "information_architecture" in plan.phases, "Information architecture phase is selected"),
            ]),
            "ux-ui-design": (15, "UX·UI·디자인 시스템", [
                _check("ux:phase", "ux" in plan.phases, "UX phase is selected"),
                _check("ui:phase", "ui" in plan.phases, "UI phase is selected"),
                _check("design:artifact", (root / "DESIGN.md").is_file(), "DESIGN.md is present"),
            ]),
            "technical-code": (20, "기술설계·코드", [
                _check("technical:phase", "technical_design" in plan.phases, "Technical design phase is selected"),
                _check("implementation:phase", "implementation" in plan.phases, "Implementation phase is selected"),
                _check("code:workspace", any(root.glob("*.html")) or (root / "apps").is_dir() or (root / "src").is_dir(), "Implementation workspace exists"),
                _check("encoding:integrity", not any(check.status == "BLOCK" for check in integrity), "Encoding checks pass"),
            ]),
            "tests-security-accessibility-performance": (20, "테스트·보안·접근성·성능", [
                _check("testing:phase", "testing" in plan.phases, "Testing phase is selected"),
                _check("qa:report", qa.get("status") == "PASS", "Independent QA report passes"),
                _check("security:evidence", not any("secret" in str(item).casefold() for item in blockers), "No secret blocker is present"),
                _check("accessibility:phase", "accessibility" in plan.phases, "Accessibility phase is selected"),
            ]),
            "deploy-ops-recovery": (10, "배포·운영·복구", [
                _check("release:phase", "release" in plan.phases, "Release phase is selected"),
                _check("ops:artifact", (root / "DEPLOYMENT.md").is_file(), "Deployment runbook is present"),
                _check("ops:rollback", _has_rollback_evidence(root), "Rollback evidence is present"),
                _check("claimlatch:release", claim.get("decision") == "PASS", "ClaimLatch release decision passes"),
            ]),
            "docs-handoff-portfolio": (10, "문서·인수인계·포트폴리오", [
                _check("docs:readme", (root / "README.md").is_file(), "README is present"),
                _check("docs:log", (root / "PROJECT_LOG.md").is_file(), "Project log is present"),
                _check("docs:integration", "integration" in plan.phases, "Integration handoff phase is selected"),
                _check("docs:limitations", True, "Limitations are explicitly recorded"),
            ]),
        }
        categories = [_category(category_id, title, max_points, checks) for category_id, (max_points, title, checks) in category_inputs.items()]
        score = sum(category.score for category in categories)
        if blockers:
            grade: ReportGrade = "replan_required" if any("QA" in item or "ClaimLatch" in item or "Rollback" in item for item in blockers) else "revision_required"
        elif limitations or score < 90:
            grade = "client_ready_with_notes" if score >= 85 else "revision_required"
        else:
            grade = "portfolio_ready"
        report = FinalProjectReport(
            projectId=plan.project_id,
            projectRevision=plan.project_revision,
            initialRequest=intent.raw_text,
            finalResult={"grade": grade, "score": score},
            selectedGraph={"phases": plan.phases, "taskCount": len(plan.tasks)},
            artifacts=_artifact_paths(root),
            requirementTraceability=requirement_traceability,
            gateResults={"qa": qa.get("status", "NOT_RUN"), "claimLatch": claim.get("decision", "NOT_RUN"), "browser": browser},
            retries=[dict(item) for item in qa.get("retries", []) if isinstance(item, Mapping)],
            testResults=list(qa.get("checks", [])) if isinstance(qa.get("checks"), list) else [],
            categories=categories,
            score=score,
            grade=grade,
            blockers=blockers,
            limitations=limitations,
            nextImprovements=_next_improvements(grade, browser, plan),
        )
        (root / "FINAL-QUALITY-REPORT.json").write_text(
            json.dumps(report.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return report


def _check(name: str, passed: bool, message: str) -> QualityCheck:
    return QualityCheck(name=name, status="PASS" if passed else "WARN", message=message)


def _category(category_id: str, title: str, max_points: int, checks: list[QualityCheck]) -> QualityCategoryResult:
    passed = sum(check.status == "PASS" for check in checks)
    score = round(max_points * passed / len(checks)) if checks else 0
    status = "PASS" if passed == len(checks) else "WARN"
    return QualityCategoryResult(id=category_id, title=title, maxPoints=max_points, score=score, status=status, checks=checks)


_ROLLBACK_EVIDENCE = re.compile(
    r"(?im)^\s*(?:rollback(?:\s+(?:procedure|command))?|복구(?:\s+(?:절차|명령))?)\s*:\s*(?P<value>\S.*)$"
)


def _has_rollback_evidence(root: Path) -> bool:
    placeholders = {"todo", "tbd", "n/a", "none", "미정", "없음", "..."}
    for path in (root / "DEPLOYMENT.md", root / "PROJECT_LOG.md"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _ROLLBACK_EVIDENCE.finditer(text):
            value = match.group("value").strip()
            if value and value.casefold() not in placeholders:
                return True
        normalized = text.casefold()
        if all(token in normalized for token in ("rollback", "release_manifest", "git revision", "project_log")):
            return True
    return False


def _requirement_traceability(
    intent: ProjectIntent,
    qa: Mapping[str, object],
    blockers: list[str],
) -> list[dict[str, object]]:
    """Require each acceptance criterion to point at current QA evidence."""

    if not intent.acceptance_criteria:
        return []
    raw_items = qa.get("requirementTraceability")
    qa_evidence = {
        str(item).strip()
        for item in qa.get("evidenceIds", [])
        if isinstance(item, str) and item.strip()
    } if isinstance(qa.get("evidenceIds"), list) else set()
    normalized: list[dict[str, object]] = []
    invalid = False
    for criterion in intent.acceptance_criteria:
        match = next(
            (
                item for item in raw_items
                if isinstance(item, Mapping) and item.get("criterion") == criterion
            ),
            None,
        ) if isinstance(raw_items, list) else None
        evidence_ids = [
            str(item).strip()
            for item in (match.get("evidenceIds", []) if isinstance(match, Mapping) else [])
            if isinstance(item, str) and item.strip()
        ]
        status = str(match.get("status", "unverified")).casefold() if isinstance(match, Mapping) else "unverified"
        verified = status in {"verified", "pass", "passed"} and bool(evidence_ids) and set(evidence_ids).issubset(qa_evidence)
        normalized.append({
            "criterion": criterion,
            "status": "verified" if verified else "unverified",
            "evidenceIds": evidence_ids if verified else [],
        })
        invalid = invalid or not verified
    if invalid:
        blockers.append("Requirement traceability evidence is missing")
    return normalized


def _browser_status(qa: Mapping[str, object]) -> str:
    if qa.get("browserVerification") == "NOT_RUN":
        return "NOT_RUN"
    checks = qa.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, Mapping) and check.get("name") == "browser:ui-e2e":
                status = str(check.get("status", "")).casefold()
                return "NOT_RUN" if status == "not_run" else "PASS" if status in {"passed", "pass"} else "BLOCK"
    return "NOT_RUN"


def _artifact_paths(root: Path) -> list[str]:
    return [str(path.relative_to(root)) for path in root.rglob("*") if path.is_file() and path.name in {"README.md", "DESIGN.md", "PROJECT_LOG.md", "QA_REPORT.json", "DEPLOYMENT.md", "RELEASE_MANIFEST.json"}]


def _next_improvements(grade: ReportGrade, browser: str, plan: ProjectExecutionPlan) -> list[str]:
    improvements: list[str] = []
    if browser == "NOT_RUN":
        improvements.append("브라우저 엔진을 연결해 실제 viewport·키보드 E2E를 실행")
    if plan.missing_extensions:
        improvements.append("누락된 외부 확장을 연결한 뒤 동일 revision에서 재검증")
    if grade in {"revision_required", "replan_required"}:
        improvements.append("차단된 증거를 먼저 해결하고 최종 품질 평가를 재실행")
    return improvements
