from __future__ import annotations

import os
import hashlib
import json
import subprocess
import sys
import time
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.project_runtime.git_workspace import GitWorkspaceError, record_workspace
from app.release.manifest import build_release_manifest
from app.iseol.quality import ProductQualityProfile


@dataclass
class LocalRuntimeResult:
    process: subprocess.Popen[bytes]
    url: str
    auth_mode: str


@dataclass
class PreparedWebRun:
    qa_report: dict[str, Any]
    qa_report_path: str
    artifacts: list[dict[str, Any]]


@dataclass
class WebRunResult:
    status: str
    reason: str
    qa_report_path: str
    release_manifest_path: str | None
    git_branch: str | None = None
    git_commit: str | None = None


class WebProjectRunner:
    """Start and stop a generated web project without external credentials."""

    def start(self, workspace: str | Path, *, port: int = 8787) -> LocalRuntimeResult:
        root = Path(workspace).resolve()
        if not (root / "apps/api/server.py").is_file():
            raise ValueError("Generated web project is missing apps/api/server.py")
        env = os.environ.copy()
        env.update({"API_HOST": "127.0.0.1", "API_PORT": str(port), "AUTH_MODE": "demo", "PYTHONIOENCODING": "utf-8"})
        process = subprocess.Popen(
            [sys.executable, str(root / "apps/api/server.py")],
            cwd=root / "apps/api",
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Generated web API exited before becoming ready")
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=0.5) as response:
                    if response.status == 200:
                        return LocalRuntimeResult(process=process, url=url, auth_mode="demo")
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        self.stop(LocalRuntimeResult(process=process, url=url, auth_mode="demo"))
        raise TimeoutError("Generated web API did not become ready")

    def prepare(self, *, project_id: str, project_revision: str, workspace: str | Path) -> PreparedWebRun:
        root = Path(workspace).resolve()
        checks = []
        for relative in (
            "apps/web/index.html", "apps/web/src/app/main.js", "apps/web/src/entities/todo/model.js",
            "apps/web/src/shared/lib/api.js", "apps/web/src/pages/home/ui.js",
            "apps/web/src/shared/ui/styles.css", "apps/api/server.py",
            "apps/api/store.py", "packages/auth/README.md", "packages/db/README.md",
            ".env.example", "DEPLOYMENT.md",
        ):
            path = root / relative
            checks.append(self._check("required-file:" + relative, path.is_file(), path))
            if path.is_file():
                try:
                    path.read_text(encoding="utf-8")
                    checks.append(self._check("utf8:" + relative, True, path))
                except UnicodeDecodeError:
                    checks.append(self._check("utf8:" + relative, False, path))
        api = root / "apps/api/server.py"
        syntax = subprocess.run([sys.executable, "-m", "py_compile", str(api)], capture_output=True, text=True, check=False)
        checks.append(self._check("syntax:apps/api/server.py", syntax.returncode == 0, api, syntax.stderr.strip()))
        checks.append(self._check("auth:production-config-gated", "awaiting_configuration" in self._read(api), api))
        checks.append(self._check("deployment:truthful-handoff", "ClaimLatch" in self._read(root / "DEPLOYMENT.md"), root / "DEPLOYMENT.md"))
        store = root / "apps/api/store.py"
        page = root / "apps/web/src/pages/home/ui.js"
        checks.append(self._check(
            "product-baseline:todo-workflow",
            all(token in self._read(path) for path, token in ((api, "/api/todos/stats"), (store, "def delete"), (store, "due_date"), (page, "진행률"), (page, "삭제"))),
            page,
        ))
        index = root / "apps/web/index.html"
        styles = root / "apps/web/src/shared/ui/styles.css"
        checks.append(self._check(
            "responsive:viewport",
            'name="viewport"' in self._read(index).lower(),
            index,
        ))
        checks.append(self._check("responsive:media-query", "@media" in self._read(styles), styles))
        node = shutil.which("node")
        for relative in (
            "apps/web/src/app/main.js",
            "apps/web/src/entities/todo/model.js",
            "apps/web/src/shared/lib/api.js",
            "apps/web/src/pages/home/ui.js",
        ):
            path = root / relative
            if node is None:
                checks.append(self._check("syntax:" + relative, False, path, "node is required for frontend syntax verification"))
                continue
            syntax = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, check=False)
            checks.append(self._check("syntax:" + relative, syntax.returncode == 0, path, syntax.stderr.strip()))
        try:
            runtime = self.start(root, port=self._free_port())
            try:
                checks.append(self._check("e2e:health", self._json_get(runtime.url + "/api/health").get("status") == "ok", api))
                before = self._http(runtime.url + "/api/session", method="POST", payload={"mode": "demo"})
                created = self._http(runtime.url + "/api/todos", method="POST", payload={"title": "release check", "priority": "high"})
                checks.append(self._check("e2e:demo-auth-and-crud", before.get("mode") == "demo" and created.get("priority") == "high", api))
            finally:
                self.stop(runtime)
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            checks.append(self._check("e2e:health", False, api, str(exc)))
            checks.append(self._check("e2e:demo-auth-and-crud", False, api, str(exc)))
        failed = [item for item in checks if item["status"] != "passed"]
        if failed:
            raise ValueError("Web scaffold verification failed: " + "; ".join(item["name"] for item in failed))
        evidence_ids = [item["evidenceId"] for item in checks]
        report = {
            "schemaVersion": 1, "id": f"qa-{project_id}-{project_revision}",
            "projectId": project_id, "projectRevision": project_revision,
            "status": "PASS", "independent": True, "runner": "EEEE.WebProjectRunner",
            "runtimeProfile": "web_app", "authMode": "demo",
            "deploymentReadiness": "awaiting_configuration",
            "createdAt": datetime.now(timezone.utc).isoformat(), "checks": checks,
            "evidenceIds": evidence_ids,
        }
        qa_path = root / "QA_REPORT.json"
        qa_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        quality = ProductQualityProfile.web_app().evaluate(root, require_release_evidence=False)
        if quality.decision != "PASS":
            raise ValueError("Web portfolio quality profile failed: " + "; ".join(check.message for check in quality.checks if check.status == "BLOCK"))
        report["qualityProfile"] = quality.model_dump(mode="json")
        qa_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return PreparedWebRun(
            qa_report=report, qa_report_path=str(qa_path),
            artifacts=[{"id": "web-source", "path": "apps", "evidence_ids": evidence_ids}, {"id": "web-qa", "path": "QA_REPORT.json", "evidence_ids": evidence_ids}],
        )

    def run(self, *, project_id: str, project_revision: str, workspace: str | Path, claim_latch: Mapping[str, Any]) -> WebRunResult:
        prepared = self.prepare(project_id=project_id, project_revision=project_revision, workspace=workspace)
        return self.finalize(project_id=project_id, project_revision=project_revision, workspace=workspace, prepared=prepared, claim_latch=claim_latch)

    def finalize(self, *, project_id: str, project_revision: str, workspace: str | Path, prepared: PreparedWebRun, claim_latch: Mapping[str, Any]) -> WebRunResult:
        if claim_latch.get("decision") != "PASS" or not claim_latch.get("receiptId"):
            return WebRunResult("BLOCKED", "ClaimLatch release verification did not PASS", prepared.qa_report_path, None)
        manifest = build_release_manifest(project_id=project_id, project_revision=project_revision, workspace=str(Path(workspace).resolve()), artifacts=prepared.artifacts, qa_report=prepared.qa_report, claim_latch=dict(claim_latch))
        manifest_path = Path(workspace).resolve() / "RELEASE_MANIFEST.json"
        manifest_path.write_text(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        quality = ProductQualityProfile.web_app().evaluate(Path(workspace).resolve())
        if quality.decision != "PASS":
            return WebRunResult("BLOCKED", "Web portfolio quality profile did not PASS: " + "; ".join(check.message for check in quality.checks if check.status == "BLOCK"), prepared.qa_report_path, str(manifest_path))
        try:
            git = record_workspace(workspace, project_id=project_id, message="feat(web): generate verified web app")
        except GitWorkspaceError as exc:
            return WebRunResult("BLOCKED", f"Git workspace recording failed: {exc}", prepared.qa_report_path, str(manifest_path))
        return WebRunResult("PASS", "Web project passed local auth/API QA and ClaimLatch release verification", prepared.qa_report_path, str(manifest_path), git.branch, git.commit)

    @staticmethod
    def _free_port() -> int:
        import socket
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    @staticmethod
    def _json_get(url: str) -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.loads(response.read())

    @staticmethod
    def _http(url: str, *, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), method=method, headers={"content-type": "application/json"})
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read())

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    @staticmethod
    def _check(name: str, passed: bool, path: Path, detail: str | None = None) -> dict[str, Any]:
        digest = hashlib.sha256()
        if path.is_file(): digest.update(path.read_bytes())
        digest.update(name.encode("utf-8"))
        result = {"name": name, "status": "passed" if passed else "failed", "evidenceId": "evidence-" + digest.hexdigest()[:16], "path": str(path)}
        if detail: result["detail"] = detail
        return result

    @staticmethod
    def stop(runtime: LocalRuntimeResult) -> None:
        if runtime.process.poll() is None:
            runtime.process.terminate()
            try:
                runtime.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                runtime.process.kill()
                runtime.process.wait(timeout=3)
