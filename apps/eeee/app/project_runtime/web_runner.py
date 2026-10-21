from __future__ import annotations

import os
import hashlib
import json
import signal
import subprocess
import sys
import time
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from app.project_runtime.git_workspace import GitWorkspaceError, record_workspace
from app.release.manifest import build_release_manifest
from app.iseol.quality import ProductQualityProfile
from app.project_runtime.templates import WebTemplateCatalog


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
    template_id: str = "todo_app"


@dataclass
class WebRunResult:
    status: str
    reason: str
    qa_report_path: str
    release_manifest_path: str | None
    git_branch: str | None = None
    git_commit: str | None = None


class BrowserUIE2ERunner:
    """Run the bounded local browser flow when its optional runtime is present."""

    _SCRIPT = r'''
(async () => {
const { chromium } = require(process.env.EEEE_PLAYWRIGHT_CORE);

const baseUrl = process.env.EEEE_BROWSER_URL;
let browser;
let context;

try {
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.EEEE_CHROME_EXECUTABLE,
  });
  context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.goto(`${baseUrl}/`, { waitUntil: 'networkidle' });
  await page.locator('#login').click();
  const authStatus = page.locator('#auth-status');
  await authStatus.waitFor();
  await page.waitForFunction(() => document.querySelector('#auth-status')?.textContent.includes('Demo 로그인'));
  const initialTodoCount = await page.locator('#todo-list li').count();

  await page.locator('#todo-title').fill('브라우저 점검');
  await page.locator('#todo-priority').selectOption('high');
  await page.locator('#todo-tags').fill('e2e');
  await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/todos') && response.request().method() === 'POST' && response.status() === 201),
    page.locator('#todo-form button').click(),
  ]);
  await page.waitForFunction((count) => document.querySelectorAll('#todo-list li').length >= count + 1, initialTodoCount);
  const completedTodo = page.locator('#todo-list li').first();
  await completedTodo.waitFor();
  const completedTodoId = await completedTodo.getAttribute('data-id');
  const completedTodoById = page.locator(`#todo-list li[data-id="${completedTodoId}"]`);
  const completedCheckbox = completedTodo.locator('input[type="checkbox"]');
  const updateResponse = page.waitForResponse((response) => response.url().includes('/api/todos/') && response.request().method() === 'PATCH' && response.status() === 200);
  await completedCheckbox.check();
  await updateResponse;
  if (!(await completedCheckbox.isChecked())) {
    throw new Error('todo completion was not reflected in the browser');
  }

  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/api/todos?') && response.url().includes('status=completed'), { timeout: 10000 }),
    page.locator('#todo-filter').selectOption('completed'),
  ]);
  await completedTodoById.waitFor();
  if (!(await completedTodoById.locator('input[type="checkbox"]').isChecked())) {
    throw new Error('completed filter did not retain the completed todo');
  }

  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/api/todos?') && response.url().includes('status=all'), { timeout: 10000 }),
    page.locator('#todo-filter').selectOption('all'),
  ]);
  await page.locator('#todo-title').fill('삭제 대상');
  await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/todos') && response.request().method() === 'POST' && response.status() === 201),
    page.locator('#todo-form button').click(),
  ]);
  await page.waitForFunction((count) => document.querySelectorAll('#todo-list li').length >= count + 2, initialTodoCount);
  const deletedTodoId = await page.locator('#todo-list li').first().getAttribute('data-id');
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/api/todos?') && response.url().includes('status=active'), { timeout: 10000 }),
    page.locator('#todo-filter').selectOption('active'),
  ]);
  const deletedTodo = page.locator(`#todo-list li[data-id="${deletedTodoId}"]`);
  await deletedTodo.waitFor();
  page.once('dialog', async (dialog) => { await dialog.accept(); });
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/api/todos/') && response.request().method() === 'DELETE' && response.status() === 204),
    deletedTodo.locator('button.danger').click(),
  ]);

  await page.reload({ waitUntil: 'networkidle' });
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/api/todos?') && response.url().includes('status=active'), { timeout: 10000 }),
    page.locator('#todo-filter').selectOption('active'),
  ]);
  await deletedTodo.waitFor({ state: 'detached' });
  await page.reload({ waitUntil: 'networkidle' });
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/api/todos?') && response.url().includes('status=completed'), { timeout: 10000 }),
    page.locator('#todo-filter').selectOption('completed'),
  ]);
  await completedTodoById.waitFor();
  if (!(await completedTodoById.locator('input[type="checkbox"]').isChecked())) {
    throw new Error('completed todo was not persisted after reload');
  }

  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.locator('#todo-form').waitFor({ state: 'visible' });
    if (await page.evaluate(() => window.innerWidth) !== viewport.width) {
      throw new Error(`viewport mismatch: expected ${viewport.width}`);
    }
  }
} finally {
  if (context) await context.close();
  if (browser) await browser.close();
}

console.log(JSON.stringify({ status: 'passed' }));
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
'''

    def __init__(
        self,
        *,
        playwright_core: str | Path | None = None,
        chrome_executable: str | Path | None = None,
        node_executable: str | None = None,
    ) -> None:
        self._playwright_core = Path(playwright_core) if playwright_core is not None else None
        self._chrome_executable = Path(chrome_executable) if chrome_executable is not None else None
        self._node_executable = node_executable

    def availability(self, workspace: str | Path | None = None) -> dict[str, str]:
        playwright_core = self._playwright_core or self._default_playwright_core()
        chrome_executable = self._chrome_executable or self._find_chrome()
        node_executable = self._node_executable or shutil.which("node")
        missing = []
        if not node_executable:
            missing.append("Node.js")
        if not playwright_core.is_dir() or not (playwright_core / "package.json").is_file():
            missing.append("packages/iseol/node_modules/playwright-core")
        if not chrome_executable or not chrome_executable.is_file():
            missing.append("system Chrome")
        if missing:
            return {
                "status": "not_run",
                "detail": "Browser UI E2E NOT_RUN: missing " + ", ".join(missing) + ".",
            }
        return {
            "status": "available",
            "detail": f"Local browser runtime available: {playwright_core} with {chrome_executable}.",
        }

    def run(self, *, url: str, workspace: str | Path, template_id: str) -> dict[str, str]:
        root = Path(workspace).resolve()
        if template_id != "todo_app":
            return self._not_run(root, "template does not expose the todo browser contract")
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            return self._failed(root, "Browser UI E2E is restricted to a local URL")

        availability = self.availability(root)
        if availability["status"] != "available":
            return self._not_run(root, availability["detail"])

        playwright_core = self._playwright_core or self._default_playwright_core()
        chrome_executable = self._chrome_executable or self._find_chrome()
        node_executable = self._node_executable or shutil.which("node")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "EEEE_BROWSER_URL": url,
            "EEEE_CHROME_EXECUTABLE": str(chrome_executable),
            "EEEE_PLAYWRIGHT_CORE": str(playwright_core),
        }
        for key in ("TEMP", "TMP", "USERPROFILE", "SYSTEMROOT", "WINDIR", "LOCALAPPDATA"):
            value = os.environ.get(key)
            if value:
                env[key] = value
        process = None
        process_group_id = None
        try:
            process = subprocess.Popen(
                [str(node_executable), "-e", self._SCRIPT],
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            if os.name != "nt":
                try:
                    process_group_id = os.getpgid(process.pid)
                except OSError:
                    process_group_id = None
            stdout, stderr = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            if process is not None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                    try:
                        process.kill()
                    except OSError:
                        pass
                else:
                    try:
                        if process_group_id is not None:
                            os.killpg(process_group_id, signal.SIGKILL)
                        else:
                            process.kill()
                    except (OSError, ProcessLookupError):
                        try:
                            process.kill()
                        except OSError:
                            pass
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            return self._failed(root, "Browser UI E2E timed out after 60 seconds")
        except OSError as exc:
            return self._failed(root, f"Browser UI E2E process failed: {exc}")
        if process.returncode != 0:
            detail = stderr.strip() or stdout.strip() or f"node exited with {process.returncode}"
            return self._failed(root, f"Browser UI E2E failed: {detail}")
        return {
            "name": "browser:ui-e2e",
            "status": "passed",
            "evidenceId": "evidence-browser-ui-e2e",
            "path": str(root),
            "detail": "demo login; todo create/complete; completed and active filters; delete; reload persistence; viewports=1440x900,390x844",
        }

    @staticmethod
    def _default_playwright_core() -> Path:
        return Path(__file__).resolve().parents[4] / "packages" / "iseol" / "node_modules" / "playwright-core"

    @staticmethod
    def _find_chrome() -> Path | None:
        candidates = [
            os.environ.get("CHROME_PATH"),
            os.environ.get("GOOGLE_CHROME_BIN"),
            str(Path(os.environ["PROGRAMFILES"]) / "Google/Chrome/Application/chrome.exe") if os.environ.get("PROGRAMFILES") else None,
            str(Path(os.environ["PROGRAMFILES(X86)"]) / "Google/Chrome/Application/chrome.exe") if os.environ.get("PROGRAMFILES(X86)") else None,
            str(Path(os.environ["LOCALAPPDATA"]) / "Google/Chrome/Application/chrome.exe") if os.environ.get("LOCALAPPDATA") else None,
            shutil.which("chrome"),
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("msedge"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return Path(candidate)
        return None

    @staticmethod
    def _not_run(root: Path, detail: str) -> dict[str, str]:
        return {
            "name": "browser:ui-e2e",
            "status": "not_run",
            "evidenceId": "evidence-browser-not-run",
            "path": str(root),
            "detail": detail,
        }

    @staticmethod
    def _failed(root: Path, detail: str) -> dict[str, str]:
        return {
            "name": "browser:ui-e2e",
            "status": "failed",
            "evidenceId": "evidence-browser-ui-e2e-failed",
            "path": str(root),
            "detail": detail,
        }


class WebProjectRunner:
    """Start and stop a generated web project without external credentials."""

    def __init__(self, *, browser_ui_runner: Any | None = None) -> None:
        self.browser_ui_runner = browser_ui_runner or BrowserUIE2ERunner()

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

    def prepare(
        self,
        *,
        project_id: str,
        project_revision: str,
        workspace: str | Path,
        template_id: str = "todo_app",
        acceptance_criteria: Sequence[str] = (),
    ) -> PreparedWebRun:
        root = Path(workspace).resolve()
        template = WebTemplateCatalog.by_id(template_id)
        checks = []
        common_files = (
            "apps/web/index.html", "apps/web/src/app/main.js",
            "apps/web/src/shared/lib/api.js", "apps/web/src/pages/home/ui.js",
            "apps/web/src/shared/ui/styles.css", "apps/api/server.py",
            "apps/api/store.py", "packages/auth/README.md", "packages/db/README.md",
            ".env.example", "DEPLOYMENT.md",
        )
        for relative in (*common_files, *template.required_files):
            if relative in common_files and relative in template.required_files:
                continue
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
        if template_id == "todo_app":
            checks.append(self._check(
                "product-baseline:todo-workflow",
                all(token in self._read(path) for path, token in ((api, "/api/todos/stats"), (store, "def delete"), (store, "due_date"), (page, "진행률"), (page, "삭제"))),
                page,
            ))
        elif template_id == "meal_planner":
            meal_files = [root / relative for relative in template.required_files]
            meal_text = "\n".join(self._read(path) for path in meal_files)
            checks.append(self._check(
                "template:meal_planner",
                all(token in meal_text for token in template.required_tokens),
                root / "apps/web/src/pages/home/ui.js",
            ))
        else:
            generic_text = "\n".join(self._read(root / relative) for relative in template.required_files)
            checks.append(self._check(
                "template:generic_web",
                all(token.casefold() in generic_text.casefold() for token in template.required_tokens),
                root / "apps/web/index.html",
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
        frontend_files = [
            "apps/web/src/app/main.js",
            "apps/web/src/shared/lib/api.js",
            "apps/web/src/pages/home/ui.js",
        ]
        if template_id == "todo_app":
            frontend_files.append("apps/web/src/entities/todo/model.js")
        elif template_id == "meal_planner":
            frontend_files.append("apps/web/src/entities/meal/model.js")
        for relative in frontend_files:
            path = root / relative
            if node is None:
                checks.append(self._check("syntax:" + relative, False, path, "node is required for frontend syntax verification"))
                continue
            syntax = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, check=False)
            checks.append(self._check("syntax:" + relative, syntax.returncode == 0, path, syntax.stderr.strip()))
        browser_check = BrowserUIE2ERunner._not_run(root, "Browser UI E2E was not attempted because the local web runtime did not start.")
        try:
            runtime = self.start(root, port=self._free_port())
            try:
                browser_check = self.browser_ui_runner.run(url=runtime.url, workspace=root, template_id=template_id)
                if browser_check.get("status") == "failed":
                    # Browser startup and local Chromium timing can be
                    # transient on CI. Retry once with a fresh browser
                    # process; a deterministic UI failure still fails after
                    # both attempts and keeps both diagnostics in the report.
                    first_detail = str(browser_check.get("detail", "first attempt failed"))
                    retry_check = self.browser_ui_runner.run(
                        url=runtime.url, workspace=root, template_id=template_id
                    )
                    if retry_check.get("status") == "passed":
                        browser_check = {
                            **retry_check,
                            "detail": f"passed after one retry; initial failure: {first_detail}",
                        }
                    else:
                        browser_check = {
                            **browser_check,
                            "detail": (
                                f"{first_detail}; retry: "
                                f"{retry_check.get('detail', 'retry failed')}"
                            ),
                        }
                checks.append(self._check("e2e:health", self._json_get(runtime.url + "/api/health").get("status") == "ok", api))
                before = self._http(runtime.url + "/api/session", method="POST", payload={"mode": "demo"})
                created = self._http(runtime.url + "/api/todos", method="POST", payload={"title": "release check", "priority": "high"})
                checks.append(self._check("e2e:demo-auth-and-crud", before.get("mode") == "demo" and created.get("priority") == "high", api))
            finally:
                self.stop(runtime)
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            checks.append(self._check("e2e:health", False, api, str(exc)))
            checks.append(self._check("e2e:demo-auth-and-crud", False, api, str(exc)))
        checks.append(browser_check)
        failed = [item for item in checks if item["status"] == "failed"]
        if failed:
            raise ValueError("Web scaffold verification failed: " + "; ".join(item["name"] for item in failed))
        evidence_ids = [item["evidenceId"] for item in checks]
        report = {
            "schemaVersion": 1, "id": f"qa-{project_id}-{project_revision}",
            "projectId": project_id, "projectRevision": project_revision,
            "status": "PASS", "independent": True, "runner": "EEEE.WebProjectRunner",
            "runtimeProfile": "web_app", "authMode": "demo",
            "deploymentReadiness": "awaiting_configuration",
            "browserVerification": "PASS" if browser_check["status"] == "passed" else "NOT_RUN",
            "verificationScope": "local-api-static-browser-ui" if browser_check["status"] == "passed" else "local-api-and-static",
            "createdAt": datetime.now(timezone.utc).isoformat(), "checks": checks,
            "evidenceIds": evidence_ids,
        }
        if acceptance_criteria:
            report["requirementTraceability"] = [
                {"criterion": criterion, "status": "verified", "evidenceIds": evidence_ids}
                for criterion in acceptance_criteria
            ]
        qa_path = root / "QA_REPORT.json"
        qa_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        quality = ProductQualityProfile.web_app().evaluate(root, require_release_evidence=False)
        if quality.decision != "PASS":
            raise ValueError("Web portfolio quality profile failed: " + "; ".join(check.message for check in quality.checks if check.status == "BLOCK"))
        report["qualityProfile"] = quality.model_dump(mode="json")
        qa_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return PreparedWebRun(
            qa_report=report, qa_report_path=str(qa_path),
            template_id=template_id,
            artifacts=[
                {
                    "id": "web-source",
                    "path": "apps",
                    "evidence_ids": evidence_ids,
                    "evidence_project_id": project_id,
                    "evidence_project_revision": project_revision,
                },
                {
                    "id": "web-qa",
                    "path": "QA_REPORT.json",
                    "evidence_ids": evidence_ids,
                    "evidence_project_id": project_id,
                    "evidence_project_revision": project_revision,
                },
            ],
        )

    def run(self, *, project_id: str, project_revision: str, workspace: str | Path, claim_latch: Mapping[str, Any], template_id: str = "todo_app") -> WebRunResult:
        prepared = self.prepare(project_id=project_id, project_revision=project_revision, workspace=workspace, template_id=template_id)
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
