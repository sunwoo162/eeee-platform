import json
import socket
import urllib.error
import urllib.request
from urllib.parse import quote

from app.project_runtime.web_scaffold import create_web_app_scaffold
from app.project_runtime.meal_planner_scaffold import MealPlannerTemplate
from app.project_runtime.web_runner import WebProjectRunner


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
    assert checks["browser:ui-e2e"]["status"] == "not_run"
    assert prepared.qa_report["browserVerification"] == "NOT_RUN"


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
