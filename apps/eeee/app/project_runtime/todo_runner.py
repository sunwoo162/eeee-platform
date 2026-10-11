from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.release.manifest import build_release_manifest
from app.iseol.quality import ProductQualityProfile
from app.project_runtime.git_workspace import GitWorkspaceError, record_workspace


class TodoRunResult:
    def __init__(
        self,
        *,
        status: str,
        reason: str,
        qa_report_path: str,
        release_manifest_path: str | None,
        git_branch: str | None = None,
        git_commit: str | None = None,
    ) -> None:
        self.status = status
        self.reason = reason
        self.qa_report_path = qa_report_path
        self.release_manifest_path = release_manifest_path
        self.git_branch = git_branch
        self.git_commit = git_commit


class PreparedTodoRun:
    def __init__(self, *, qa_report: dict[str, Any], qa_report_path: str, artifacts: list[dict[str, Any]]) -> None:
        self.qa_report = qa_report
        self.qa_report_path = qa_report_path
        self.artifacts = artifacts


class TodoProjectRunner:
    """Run the deterministic local verification stage for a generated Todo app."""

    required_files = (
        "index.html",
        "package.json",
        "DESIGN.md",
        "src/app/main.js",
        "src/entities/todo/model.js",
        "src/features/todo-create/ui.js",
        "src/features/todo-toggle/ui.js",
        "src/features/todo-edit/ui.js",
        "src/features/todo-filter/ui.js",
        "src/widgets/todo-list/ui.js",
        "src/widgets/todo-stats/ui.js",
        "src/pages/todo-page/ui.js",
        "src/shared/lib/storage.js",
        "src/shared/ui/styles.css",
        "tests/e2e/todo-flow.md",
        "tests/unit/todo-model.test.mjs",
        "tests/integration/storage-contract.md",
    )
    javascript_files = tuple(path for path in required_files if path.endswith(".js"))

    def run(
        self,
        *,
        project_id: str,
        project_revision: str,
        workspace: str | Path,
        claim_latch: Mapping[str, Any],
    ) -> TodoRunResult:
        root = Path(workspace).resolve()
        prepared = self.prepare(project_id=project_id, project_revision=project_revision, workspace=root)
        if claim_latch.get("decision") != "PASS" or not claim_latch.get("receiptId"):
            return TodoRunResult(
                status="BLOCKED",
                reason="ClaimLatch release verification did not PASS",
                qa_report_path=prepared.qa_report_path,
                release_manifest_path=None,
            )
        return self.finalize(
            project_id=project_id,
            project_revision=project_revision,
            workspace=root,
            prepared=prepared,
            claim_latch=claim_latch,
        )

    def prepare(self, *, project_id: str, project_revision: str, workspace: str | Path) -> PreparedTodoRun:
        root = Path(workspace).resolve()
        checks = self._checks(root)
        failed = [check for check in checks if check["status"] != "passed"]
        if failed:
            raise ValueError("Todo scaffold verification failed: " + "; ".join(item["name"] for item in failed))
        evidence_ids = [item["evidenceId"] for item in checks]
        qa_report = {
            "schemaVersion": 1,
            "id": f"qa-{project_id}-{project_revision}",
            "projectId": project_id,
            "projectRevision": project_revision,
            "status": "PASS",
            "independent": True,
            "runner": "EEEE.TodoProjectRunner",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "evidenceIds": evidence_ids,
        }
        qa_path = root / "QA_REPORT.json"
        qa_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        quality = ProductQualityProfile.portfolio_grade().evaluate(root, require_release_evidence=False)
        if quality.decision != "PASS":
            raise ValueError("Portfolio quality profile failed: " + "; ".join(check.message for check in quality.checks if check.status == "BLOCK"))
        qa_report["qualityProfile"] = quality.model_dump(mode="json")
        qa_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        artifacts = [
            {"id": "todo-source", "path": "src", "evidence_ids": evidence_ids},
            {"id": "todo-qa", "path": "QA_REPORT.json", "evidence_ids": evidence_ids},
        ]
        return PreparedTodoRun(qa_report=qa_report, qa_report_path=str(qa_path), artifacts=artifacts)

    def finalize(
        self,
        *,
        project_id: str,
        project_revision: str,
        workspace: str | Path,
        prepared: PreparedTodoRun,
        claim_latch: Mapping[str, Any],
    ) -> TodoRunResult:
        if claim_latch.get("decision") != "PASS" or not claim_latch.get("receiptId"):
            return TodoRunResult(
                status="BLOCKED",
                reason="ClaimLatch release verification did not PASS",
                qa_report_path=prepared.qa_report_path,
                release_manifest_path=None,
            )
        manifest = build_release_manifest(
            project_id=project_id,
            project_revision=project_revision,
            workspace=str(Path(workspace).resolve()),
            artifacts=prepared.artifacts,
            qa_report=prepared.qa_report,
            claim_latch=claim_latch,
        )
        manifest_path = Path(workspace).resolve() / "RELEASE_MANIFEST.json"
        manifest_path.write_text(
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        quality = ProductQualityProfile.portfolio_grade().evaluate(Path(workspace).resolve())
        if quality.decision != "PASS":
            return TodoRunResult(
                status="BLOCKED",
                reason="Portfolio quality profile did not PASS: " + "; ".join(check.message for check in quality.checks if check.status == "BLOCK"),
                qa_report_path=prepared.qa_report_path,
                release_manifest_path=str(manifest_path),
            )
        try:
            git = record_workspace(
                workspace, project_id=project_id,
                message="feat(todo): generate verified todo project",
            )
        except GitWorkspaceError as exc:
            return TodoRunResult(
                status="BLOCKED", reason=f"Git workspace recording failed: {exc}",
                qa_report_path=prepared.qa_report_path,
                release_manifest_path=str(manifest_path),
            )
        return TodoRunResult(
            status="PASS",
            reason="Todo project passed independent QA and ClaimLatch release verification",
            qa_report_path=prepared.qa_report_path,
            release_manifest_path=str(manifest_path),
            git_branch=git.branch,
            git_commit=git.commit,
        )

    def _checks(self, root: Path) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        for relative in self.required_files:
            path = root / relative
            passed = path.is_file()
            checks.append(self._check("required-file:" + relative, passed, path))
            if passed:
                try:
                    path.read_text(encoding="utf-8")
                    checks.append(self._check("utf8:" + relative, True, path))
                except UnicodeDecodeError:
                    checks.append(self._check("utf8:" + relative, False, path))

        package_path = root / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8")) if package_path.is_file() else {}
        checks.append(self._check(
            "package:start-script",
            package.get("scripts", {}).get("start") == "python -m http.server 4173",
            package_path,
        ))
        checks.append(self._check(
            "package:test-script",
            package.get("scripts", {}).get("test") == "node --test tests/unit/todo-model.test.mjs",
            package_path,
        ))
        main = root / "src/app/main.js"
        checks.append(self._check("todo:dom-mount", "renderTodoPage" in self._read(main), main))
        checks.append(self._check("todo:persistence", "localStorage" in self._read(root / "src/shared/lib/storage.js"), root / "src/shared/lib/storage.js"))
        page = self._read(root / "src/pages/todo-page/ui.js")
        model = self._read(root / "src/entities/todo/model.js")
        styles = self._read(root / "src/shared/ui/styles.css")
        checks.append(self._check("todo:dashboard", "data-stat" in page and "progress-panel" in page, root / "src/pages/todo-page/ui.js"))
        checks.append(self._check("todo:editing-and-filtering", "data-filter" in page and "updateTodoAt" in page, root / "src/pages/todo-page/ui.js"))
        checks.append(self._check("todo:priority-and-due-date", "priority" in model and "dueDate" in model, root / "src/entities/todo/model.js"))
        checks.append(self._check("todo:responsive-design", "@media" in styles and "focus-visible" in styles, root / "src/shared/ui/styles.css"))
        for relative in self.javascript_files:
            path = root / relative
            if path.is_file():
                completed = subprocess.run(
                    ["node", "--check", str(path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                checks.append(self._check("syntax:" + relative, completed.returncode == 0, path, completed.stderr.strip()))
        unit_test = subprocess.run(
            ["node", "--test", str(root / "tests/unit/todo-model.test.mjs")],
            capture_output=True,
            text=True,
            check=False,
        )
        checks.append(self._check("unit:todo-model", unit_test.returncode == 0, root / "tests/unit/todo-model.test.mjs", unit_test.stdout.strip() or unit_test.stderr.strip()))
        e2e = root / "tests/e2e/todo-flow.md"
        scenario = self._read(e2e).lower()
        checks.append(self._check("e2e:scenario", all(token in scenario for token in ("새로고침", "삭제", "수정", "반응형", "검색")), e2e))
        return checks

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    @staticmethod
    def _check(name: str, passed: bool, path: Path, detail: str | None = None) -> dict[str, Any]:
        digest = hashlib.sha256()
        if path.is_file():
            digest.update(path.read_bytes())
        digest.update(name.encode("utf-8"))
        return {
            "name": name,
            "status": "passed" if passed else "failed",
            "evidenceId": "evidence-" + digest.hexdigest()[:16],
            "path": str(path),
            **({"detail": detail} if detail else {}),
        }
