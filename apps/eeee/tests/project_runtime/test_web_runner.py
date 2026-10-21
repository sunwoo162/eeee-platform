import json
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from urllib.parse import quote
from pathlib import Path

import pytest

from app.project_runtime.web_scaffold import create_web_app_scaffold
from app.project_runtime.meal_planner_scaffold import MealPlannerTemplate
from app.project_runtime.web_runner import BrowserUIE2ERunner, WebProjectRunner


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request(url, method="GET", payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read()
            return response.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_web_runner_executes_demo_login_and_authorized_todo_crud(tmp_path):
    root = tmp_path / "web-project"
    create_web_app_scaffold(root, "Todo Web")
    runner = WebProjectRunner()
    runtime = runner.start(root, port=_port())

    try:
        assert _request(runtime.url + "/api/health")[1]["status"] == "ok"
        page_request = urllib.request.urlopen(runtime.url + "/", timeout=5)
        assert page_request.status == 200
        assert b"Gleave Web App" in page_request.read()
        assert _request(runtime.url + "/api/session")[0] == 401
        assert _request(runtime.url + "/api/todos")[0] == 401
        assert _request(runtime.url + "/api/session", "POST", {"mode": "demo"})[0] == 200
        created = _request(runtime.url + "/api/todos", "POST", {"title": "배포 전 점검", "priority": "high"})
        assert created[0] == 201
        assert created[1]["priority"] == "high"
        updated = _request(runtime.url + "/api/todos/" + created[1]["id"], "PATCH", {"completed": True})
        assert updated[1]["completed"] is True
    finally:
        runner.stop(runtime)


def test_web_runner_reports_production_oauth_as_unconfigured(tmp_path):
    root = tmp_path / "web-project"
    create_web_app_scaffold(root, "Todo Web")
    runner = WebProjectRunner()
    runtime = runner.start(root, port=_port())

    try:
        status, payload = _request(runtime.url + "/api/session", "POST", {"mode": "google"})
        assert status == 409
        assert payload["error"] == "awaiting_configuration"
    finally:
        runner.stop(runtime)


def test_web_runner_writes_qa_and_release_manifest_only_after_claimlatch_pass(tmp_path):
    root = tmp_path / "web-project"
    create_web_app_scaffold(root, "Todo Web")
    result = WebProjectRunner().run(
        project_id="project-web",
        project_revision="rev-1",
        workspace=root,
        claim_latch={"decision": "PASS", "receiptId": "receipt-1", "claimLatchReportId": "report-1"},
    )

    assert result.status == "PASS"
    assert (root / "QA_REPORT.json").is_file()
    assert (root / "RELEASE_MANIFEST.json").is_file()
    assert result.git_commit and len(result.git_commit) == 40


def test_web_runner_does_not_release_when_browser_e2e_was_not_run(tmp_path):
    root = tmp_path / "web-project"
    create_web_app_scaffold(root, "Todo Web")

    class NotRunBrowserUIE2ERunner:
        def run(self, *, url, workspace, template_id):
            return {
                "name": "browser:ui-e2e",
                "status": "not_run",
                "evidenceId": "evidence-browser-not-run",
                "path": str(workspace),
                "detail": "browser runtime is not installed",
            }

    runner = WebProjectRunner(browser_ui_runner=NotRunBrowserUIE2ERunner())
    prepared = runner.prepare(
        project_id="project-web",
        project_revision="rev-1",
        workspace=root,
    )

    assert prepared.qa_report["status"] == "WARN"
    assert prepared.qa_report["browserVerification"] == "NOT_RUN"
    prepared_with_criteria = runner.prepare(
        project_id="project-web",
        project_revision="rev-2",
        workspace=root,
        acceptance_criteria=["핵심 화면이 실행됨"],
    )
    trace = prepared_with_criteria.qa_report["requirementTraceability"][0]
    assert trace["status"] == "partial"
    assert "evidence-browser-not-run" not in trace["evidenceIds"]
    result = runner.finalize(
        project_id="project-web",
        project_revision="rev-1",
        workspace=root,
        prepared=prepared,
        claim_latch={"decision": "PASS", "receiptId": "receipt-1"},
    )

    assert result.status == "BLOCKED"
    assert "browser" in result.reason.lower()
    assert not (root / "RELEASE_MANIFEST.json").exists()


def test_web_runner_checks_frontend_contract_and_database_survives_restart(tmp_path):
    root = tmp_path / "web-project"
    create_web_app_scaffold(root, "Todo Web")
    runner = WebProjectRunner()
    runtime = runner.start(root, port=_port())

    try:
        _request(runtime.url + "/api/session", "POST", {"mode": "demo"})
        created = _request(runtime.url + "/api/todos", "POST", {"title": "persist me"})
        assert created[0] == 201
    finally:
        runner.stop(runtime)

    restarted = runner.start(root, port=_port())
    try:
        _request(restarted.url + "/api/session", "POST", {"mode": "demo"})
        status, todos = _request(restarted.url + "/api/todos")
        assert status == 200
        assert any(todo["title"] == "persist me" for todo in todos)
    finally:
        runner.stop(restarted)

    prepared = runner.prepare(project_id="project-web", project_revision="rev-1", workspace=root)
    names = {check["name"] for check in prepared.qa_report["checks"]}
    assert "syntax:apps/web/src/app/main.js" in names
    assert "responsive:viewport" in names
    assert "responsive:media-query" in names
    assert "product-baseline:todo-workflow" in names


def test_web_runner_supports_product_baseline_todo_workflow(tmp_path):
    root = tmp_path / "web-project"
    create_web_app_scaffold(root, "Todo Web")
    runner = WebProjectRunner()
    runtime = runner.start(root, port=_port())

    try:
        _request(runtime.url + "/api/session", "POST", {"mode": "demo"})
        created = _request(
            runtime.url + "/api/todos",
            "POST",
            {"title": "포트폴리오 정리", "priority": "high", "dueDate": "2030-01-01", "tags": ["portfolio"]},
        )
        todo_id = created[1]["id"]
        assert created[0] == 201
        assert created[1]["dueDate"] == "2030-01-01"
        assert created[1]["tags"] == ["portfolio"]

        status, filtered = _request(runtime.url + "/api/todos?search=" + quote("포트폴리오") + "&status=active")
        assert status == 200 and filtered[0]["id"] == todo_id
        status, stats = _request(runtime.url + "/api/todos/stats")
        assert status == 200 and stats["total"] == 1 and stats["active"] == 1

        updated = _request(runtime.url + f"/api/todos/{todo_id}", "PATCH", {"title": "완료된 포트폴리오", "completed": True})
        assert updated[0] == 200 and updated[1]["completed"] is True
        assert _request(runtime.url + f"/api/todos/{todo_id}", "DELETE")[0] == 204
        assert _request(runtime.url + "/api/todos")[1] == []
    finally:
        runner.stop(runtime)


def test_web_runner_validates_meal_template_without_claiming_browser_pass(tmp_path):
    root = tmp_path / "meal-project"
    MealPlannerTemplate.create(root, "오늘 식단")

    prepared = WebProjectRunner().prepare(
        project_id="project-meal",
        project_revision="rev-1",
        workspace=root,
        template_id="meal_planner",
    )

    checks = {item["name"]: item for item in prepared.qa_report["checks"]}
    assert checks["template:meal_planner"]["status"] == "passed"
    assert checks["browser:ui-e2e"]["status"] == "not_applicable"
    assert prepared.qa_report["browserVerification"] == "NOT_APPLICABLE"
    assert prepared.qa_report["status"] == "PASS"


def test_web_runner_generic_template_does_not_require_todo_contract(tmp_path):
    root = tmp_path / "generic-project"
    create_web_app_scaffold(root, "카페 홈페이지")

    prepared = WebProjectRunner().prepare(
        project_id="project-generic",
        project_revision="rev-1",
        workspace=root,
        template_id="generic_web",
    )

    names = {item["name"] for item in prepared.qa_report["checks"]}
    assert "template:generic_web" in names
    assert "product-baseline:todo-workflow" not in names


def test_web_runner_records_acceptance_criteria_against_qa_evidence(tmp_path):
    root = tmp_path / "generic-project"
    create_web_app_scaffold(root, "카페 홈페이지")

    class PassingBrowserUIE2ERunner:
        def run(self, *, url, workspace, template_id):
            return {
                "name": "browser:ui-e2e",
                "status": "passed",
                "evidenceId": "evidence-browser-ui-pass",
                "path": str(workspace),
                "detail": "browser verification passed",
            }

    prepared = WebProjectRunner(browser_ui_runner=PassingBrowserUIE2ERunner()).prepare(
        project_id="project-generic",
        project_revision="rev-1",
        workspace=root,
        template_id="generic_web",
        acceptance_criteria=["핵심 화면이 실행됨"],
    )

    trace = prepared.qa_report["requirementTraceability"]
    assert trace[0]["criterion"] == "핵심 화면이 실행됨"
    assert trace[0]["status"] == "verified"
    assert trace[0]["evidenceIds"] == prepared.qa_report["evidenceIds"]


def test_web_runner_runs_browser_before_api_session_smoke(tmp_path):
    root = tmp_path / "web-project"
    create_web_app_scaffold(root, "Todo Web")

    class FreshBrowserUIE2ERunner:
        def run(self, *, url, workspace, template_id):
            status, _ = _request(url + "/api/session")
            assert status == 401
            return {
                "name": "browser:ui-e2e",
                "status": "passed",
                "evidenceId": "evidence-browser-fresh-session",
                "path": str(workspace),
                "detail": "browser login starts from an unauthenticated session",
            }

    prepared = WebProjectRunner(browser_ui_runner=FreshBrowserUIE2ERunner()).prepare(
        project_id="project-web",
        project_revision="rev-1",
        workspace=root,
    )

    assert prepared.qa_report["browserVerification"] == "PASS"


def test_browser_ui_e2e_script_asserts_state_not_only_element_presence():
    script = BrowserUIE2ERunner._SCRIPT

    assert "isChecked()" in script
    assert "count()" in script
    assert "waitFor({ state: 'detached' })" in script
    assert "waitForFunction" in script


def test_browser_ui_e2e_rejects_non_local_url(tmp_path):
    runner = BrowserUIE2ERunner(
        playwright_core=tmp_path / "missing-playwright-core",
        chrome_executable=tmp_path / "missing-chrome.exe",
        node_executable=tmp_path / "missing-node.exe",
    )

    result = runner.run(
        url="http://localhost:8787@attacker.example",
        workspace=tmp_path,
        template_id="todo_app",
    )

    assert result["status"] == "failed"


def test_web_runner_records_available_browser_ui_e2e_evidence(tmp_path):
    root = tmp_path / "web-project"
    create_web_app_scaffold(root, "Todo Web")

    class StubBrowserUIE2ERunner:
        def __init__(self):
            self.calls = []

        def run(self, *, url, workspace, template_id):
            self.calls.append((url, workspace, template_id))
            return {
                "name": "browser:ui-e2e",
                "status": "passed",
                "evidenceId": "evidence-browser-ui-pass",
                "path": str(workspace),
                "detail": "demo login; todo create/complete; filter; delete; reload persistence; viewports=1440x900,390x844",
            }

    browser_runner = StubBrowserUIE2ERunner()
    prepared = WebProjectRunner(browser_ui_runner=browser_runner).prepare(
        project_id="project-web",
        project_revision="rev-1",
        workspace=root,
    )

    browser_check = next(item for item in prepared.qa_report["checks"] if item["name"] == "browser:ui-e2e")
    assert browser_check["status"] == "passed"
    assert browser_check["evidenceId"] == "evidence-browser-ui-pass"
    assert prepared.qa_report["browserVerification"] == "PASS"
    assert prepared.qa_report["verificationScope"] == "local-api-static-browser-ui"
    assert prepared.qa_report["evidenceIds"][-1] == "evidence-browser-ui-pass"
    assert len(browser_runner.calls) == 1
    assert browser_runner.calls[0][1:] == (root.resolve(), "todo_app")


def test_web_runner_retries_a_transient_browser_failure(tmp_path):
    root = tmp_path / "web-project"
    create_web_app_scaffold(root, "Todo Web")

    class FlakyBrowserUIE2ERunner:
        def __init__(self):
            self.calls = 0

        def run(self, *, url, workspace, template_id):
            self.calls += 1
            if self.calls == 1:
                return {
                    "name": "browser:ui-e2e",
                    "status": "failed",
                    "evidenceId": "evidence-browser-ui-failed",
                    "path": str(workspace),
                    "detail": "transient browser startup failure",
                }
            return {
                "name": "browser:ui-e2e",
                "status": "passed",
                "evidenceId": "evidence-browser-ui-retry-pass",
                "path": str(workspace),
                "detail": "retry passed",
            }

    browser_runner = FlakyBrowserUIE2ERunner()
    prepared = WebProjectRunner(browser_ui_runner=browser_runner).prepare(
        project_id="project-web", project_revision="rev-1", workspace=root
    )

    browser_check = next(item for item in prepared.qa_report["checks"] if item["name"] == "browser:ui-e2e")
    assert browser_check["status"] == "passed"
    assert "after one retry" in browser_check["detail"]
    assert browser_runner.calls == 2


def test_browser_ui_e2e_runner_reports_not_run_when_local_runtime_is_missing(tmp_path):
    runner = BrowserUIE2ERunner(
        playwright_core=tmp_path / "missing-playwright-core",
        chrome_executable=tmp_path / "missing-chrome.exe",
        node_executable=tmp_path / "missing-node.exe",
    )

    result = runner.availability()

    assert result["status"] == "not_run"
    assert "playwright-core" in result["detail"]
    assert "Chrome" in result["detail"]


def test_browser_ui_e2e_marks_unsupported_template_not_applicable(tmp_path):
    runner = BrowserUIE2ERunner(
        playwright_core=tmp_path / "missing-playwright-core",
        chrome_executable=tmp_path / "missing-chrome.exe",
        node_executable=tmp_path / "missing-node.exe",
    )

    result = runner.run(url="http://127.0.0.1:8787", workspace=tmp_path, template_id="meal_planner")

    assert result["status"] == "not_applicable"
    assert "todo browser contract" in result["detail"]




def test_browser_ui_e2e_script_is_valid_for_node(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    script = tmp_path / "browser-ui-e2e.js"
    script.write_text(BrowserUIE2ERunner._SCRIPT, encoding="utf-8")

    completed = subprocess.run([node, "--check", str(script)], capture_output=True, text=True, check=False)

    assert completed.returncode == 0, completed.stderr


def test_browser_ui_e2e_script_loads_playwright_core_from_node_commonjs():
    assert "require(process.env.EEEE_PLAYWRIGHT_CORE)" in BrowserUIE2ERunner._SCRIPT
    assert BrowserUIE2ERunner._SCRIPT.lstrip().startswith("(async () => {")


def test_browser_ui_e2e_runner_uses_repository_playwright_core_path():
    expected = Path(__file__).resolve().parents[4] / "packages" / "iseol" / "node_modules" / "playwright-core"

    assert BrowserUIE2ERunner._default_playwright_core() == expected
