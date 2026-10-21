"""Deterministic code-quality checks for Review and QA handoffs."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.protocol import AgentResult
from app.iseol.agents import AgentNode


class QualityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    status: Literal["PASS", "WARN", "BLOCK", "NOT_RUN"]
    message: str = Field(min_length=1)


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["PASS", "WARN", "BLOCK"]
    checks: list[QualityCheck]


class QualityArtifact(BaseModel):
    """A durable product-quality obligation, not a cosmetic checklist item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    paths: list[str]
    rationale: str


class ProductQualityProfile(BaseModel):
    """Release contract for projects intended to be portfolio-grade.

    The profile deliberately checks evidence that survives after the agents
    finish: a later reviewer can inspect the workspace without trusting the
    model's prose.  It is provider-neutral and therefore applies to local or
    hosted implementations alike.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str
    minimum_test_commands: list[str]
    required_viewports: list[str]
    artifacts: list[QualityArtifact]

    @classmethod
    def portfolio_grade(cls) -> "ProductQualityProfile":
        return cls(
            id="portfolio-grade-v1",
            minimum_test_commands=[
                "unit",
                "integration",
                "e2e",
                "responsive",
                "encoding",
                "build",
            ],
            required_viewports=["320px", "390px", "768px", "1440px"],
            artifacts=[
                QualityArtifact(id="requirements", title="Product brief and acceptance criteria", paths=["README.md"], rationale="The product goal and completion boundary must be explicit."),
                QualityArtifact(id="design-system", title="Design system and interaction decisions", paths=["DESIGN.md"], rationale="Visual quality and states must be reproducible, not implied."),
                QualityArtifact(id="architecture", title="FSD or equivalent architecture", paths=["DESIGN.md", "src"], rationale="Boundaries make later feature and plugin growth safe."),
                QualityArtifact(id="implementation", title="Runnable product implementation", paths=["index.html", "package.json", "src"], rationale="A screenshot or scaffold is not a deliverable."),
                QualityArtifact(id="test-suite", title="Unit, integration, and E2E scenarios", paths=["tests"], rationale="The primary user flow and failure paths need repeatable evidence."),
                QualityArtifact(id="responsive-accessibility", title="Responsive and accessible behavior", paths=["DESIGN.md", "tests/e2e/todo-flow.md", "src/shared/ui/styles.css"], rationale="The product must remain usable across required viewports and input modes."),
                QualityArtifact(id="security", title="Input and secret-safety review", paths=["PROJECT_LOG.md", "QA_REPORT.json"], rationale="Generated code must not turn user input or credentials into a release risk."),
                QualityArtifact(id="troubleshooting", title="Troubleshooting and decision log", paths=["PROJECT_LOG.md"], rationale="Portfolio value includes why failures and tradeoffs were handled."),
                QualityArtifact(id="runbook", title="Reproducible local runbook", paths=["README.md", "package.json"], rationale="A reviewer must be able to run the result without the agent."),
                QualityArtifact(id="release-evidence", title="QA, ClaimLatch, and release evidence", paths=["QA_REPORT.json", "RELEASE_MANIFEST.json"], rationale="Only evidence-backed output may be handed to the user."),
            ],
        )

    @classmethod
    def web_app(cls) -> "ProductQualityProfile":
        """Portfolio profile for a credential-free full-stack web app."""
        profile = cls.portfolio_grade()
        replacements = {
            "architecture": ["DESIGN.md", "apps/web/src"],
            "implementation": ["apps/web/index.html", "apps/api/server.py", "apps/api/store.py"],
            "test-suite": ["tests"],
            "responsive-accessibility": ["DESIGN.md", "tests/e2e/web-flow.md", "apps/web/src/shared/ui/styles.css"],
            "troubleshooting": ["PROJECT_LOG.md"],
            "runbook": ["README.md", "DEPLOYMENT.md"],
            "release-evidence": ["QA_REPORT.json", "RELEASE_MANIFEST.json"],
        }
        artifacts = [artifact.model_copy(update={"paths": replacements.get(artifact.id, artifact.paths)}) for artifact in profile.artifacts]
        return profile.model_copy(update={"artifacts": artifacts})

    def evaluate(
        self,
        workspace: Path,
        *,
        require_release_evidence: bool = True,
        allow_qa_warning: bool = False,
    ) -> "QualityReport":
        checks: list[QualityCheck] = []
        root = Path(workspace).resolve()
        for artifact in self.artifacts:
            if artifact.id == "release-evidence" and not require_release_evidence:
                continue
            paths = [root / path for path in artifact.paths]
            missing = [
                str(path.relative_to(root))
                for path in paths
                if not path.exists() or (path.is_file() and path.stat().st_size == 0)
                or (path.is_dir() and not any(child.is_file() for child in path.rglob("*")))
            ]
            exists = not missing
            checks.append(QualityCheck(
                name=f"quality:{artifact.id}",
                status="PASS" if exists else "BLOCK",
                message=(f"{artifact.title} evidence is present" if exists else f"Missing {artifact.title} evidence: {', '.join(missing)}"),
            ))
        report_path = root / "QA_REPORT.json"
        manifest_path = root / "RELEASE_MANIFEST.json"
        qa_valid = False
        if report_path.is_file() and report_path.stat().st_size:
            try:
                payload = json.loads(report_path.read_text(encoding="utf-8"))
                qa_evidence = payload.get("evidenceIds") if isinstance(payload, dict) else None
                checks_evidence = {
                    check.get("evidenceId")
                    for check in (payload.get("checks", []) if isinstance(payload, dict) else [])
                    if isinstance(check, dict) and isinstance(check.get("evidenceId"), str)
                }
                accepted_qa_statuses = {"PASS"}
                if allow_qa_warning:
                    accepted_qa_statuses.add("WARN")
                qa_valid = (
                    isinstance(payload, dict)
                    and payload.get("status") in accepted_qa_statuses
                    and payload.get("independent") is True
                    and isinstance(qa_evidence, list)
                    and bool(qa_evidence)
                    and set(qa_evidence).issubset(checks_evidence)
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
                qa_valid = False
        qa_status = "PASS" if qa_valid and payload.get("status") == "PASS" else "WARN" if qa_valid else "BLOCK"
        checks.append(QualityCheck(
            name="quality:qa-report",
            status=qa_status,
            message=(
                "Independent QA report is present and evidence-linked"
                if qa_status == "PASS"
                else "Independent QA report is evidence-linked but includes unexecuted checks"
                if qa_status == "WARN"
                else "Independent QA report is missing, malformed, or lacks linked evidence"
            ),
        ))
        if require_release_evidence:
            if manifest_path.is_file():
                checks.append(QualityCheck(name="quality:release-manifest", status="PASS", message="Release manifest is present"))
            else:
                checks.append(QualityCheck(name="quality:release-manifest", status="BLOCK", message="Release manifest is missing"))
        decision = "BLOCK" if any(check.status == "BLOCK" for check in checks) else (
            "WARN" if any(check.status == "WARN" for check in checks) else "PASS"
        )
        return QualityReport(decision=decision, checks=checks)


class QualityGate:
    _secret_pattern = re.compile(
        r"(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        re.IGNORECASE,
    )

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def evaluate(self, node: AgentNode, result: AgentResult) -> QualityReport:
        checks: list[QualityCheck] = []
        if not result.changed_files:
            checks.append(QualityCheck(
                name="changed-files",
                status="BLOCK",
                message="Completed agent did not report any changed files",
            ))
        existing_files: list[tuple[Path, str]] = []
        for relative in result.changed_files:
            if not isinstance(relative, str) or not relative.strip():
                checks.append(QualityCheck(
                    name="artifact-path",
                    status="BLOCK",
                    message="Reported artifact path must be a non-empty string",
                ))
                continue
            candidate = Path(relative)
            path = (self.workspace / candidate).resolve()
            try:
                path.relative_to(self.workspace.resolve())
            except ValueError:
                checks.append(QualityCheck(
                    name="artifact-path",
                    status="BLOCK",
                    message=f"Reported artifact path is outside the workspace: {relative}",
                ))
                continue
            if candidate.is_absolute() or ".." in candidate.parts:
                checks.append(QualityCheck(
                    name="artifact-path",
                    status="BLOCK",
                    message=f"Reported artifact path is not workspace-relative: {relative}",
                ))
                continue
            if not path.is_file():
                checks.append(QualityCheck(name="artifact-exists", status="BLOCK", message=f"Artifact not found for inspection: {relative}"))
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                checks.append(QualityCheck(name="encoding", status="BLOCK", message=f"File is not valid UTF-8: {relative}"))
                continue
            existing_files.append((path, text))
            if self._secret_pattern.search(text):
                checks.append(QualityCheck(name="secret-scan", status="BLOCK", message=f"Possible secret detected in {relative}"))

        if existing_files and not any(check.name == "encoding" and check.status == "BLOCK" for check in checks):
            checks.append(QualityCheck(name="encoding", status="PASS", message="Inspected files are valid UTF-8"))
        if not any(check.name == "secret-scan" and check.status == "BLOCK" for check in checks):
            checks.append(QualityCheck(name="secret-scan", status="PASS", message="No secret pattern detected"))

        if node.role == "frontend":
            index = self.workspace / "index.html"
            if index.is_file():
                text = index.read_text(encoding="utf-8", errors="replace").lower()
                checks.append(QualityCheck(
                    name="responsive-viewport",
                    status="PASS" if "name=\"viewport\"" in text or "name='viewport'" in text else "BLOCK",
                    message="Viewport metadata is present" if "viewport" in text else "index.html is missing viewport metadata",
                ))
            else:
                checks.append(QualityCheck(name="responsive-viewport", status="WARN", message="index.html was not available for viewport inspection"))

        decision = "BLOCK" if any(check.status == "BLOCK" for check in checks) else (
            "WARN" if any(check.status == "WARN" for check in checks) else "PASS"
        )
        return QualityReport(decision=decision, checks=checks)


def inspect_text_integrity(workspace: Path) -> list[QualityCheck]:
    """Inspect text encoding and tracked diff whitespace without trusting prose."""

    root = Path(workspace).resolve()
    checks: list[QualityCheck] = []
    replacement = False
    bom = False
    invalid: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in {".git", "__pycache__", "node_modules"} for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".exe", ".dll", ".woff", ".woff2", ".pyc", ".db", ".sqlite", ".sqlite3"}:
            continue
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            bom = True
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            invalid.append(str(path.relative_to(root)))
            continue
        if "\ufffd" in text:
            replacement = True
    checks.append(QualityCheck(
        name="encoding:utf8",
        status="BLOCK" if invalid else "PASS",
        message=("Invalid UTF-8 files: " + ", ".join(invalid)) if invalid else "All inspected text files are UTF-8",
    ))
    checks.append(QualityCheck(
        name="encoding:bom",
        status="BLOCK" if bom else "PASS",
        message="UTF-8 BOM detected" if bom else "No UTF-8 BOM detected",
    ))
    checks.append(QualityCheck(
        name="encoding:replacement-character",
        status="BLOCK" if replacement else "PASS",
        message="Replacement character detected" if replacement else "No replacement character detected",
    ))
    try:
        diff = subprocess.run(
            ["git", "diff", "--check", "--", "."],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if diff.returncode == 0:
            status = "PASS"
        elif "not a git repository" in diff.stderr.casefold():
            status = "NOT_RUN"
        else:
            status = "BLOCK"
        checks.append(QualityCheck(
            name="git:diff-check",
            status=status,
            message=diff.stdout.strip() or diff.stderr.strip() or "git diff --check passed",
        ))
    except OSError as exc:
        checks.append(QualityCheck(name="git:diff-check", status="NOT_RUN", message=str(exc)))
    return checks
