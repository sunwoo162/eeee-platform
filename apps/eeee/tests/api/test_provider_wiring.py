from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_app_reports_unavailable_instead_of_faking_general_chat(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: None)
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    with TestClient(create_app(settings)) as client:
        response = client.post("/api/assistant/route", json={"text": "안녕"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert "로컬 AI" in payload["message"]
    assert payload["response_verification"]["decision"] in {"WARN", "BLOCK", "BLOCKED"}
    assert "LLM_API_KEY" not in payload["message"]


def test_unconfigured_project_lane_uses_provider_neutral_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: None)
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    application = create_app(settings)
    handler = application.state.kernel.router.registry.resolve("project-execution").handler

    assert handler.agent_runtime.__class__.__name__ == "HybridAssistantRuntime"
    result = handler.agent_runtime.run(
        type("Request", (), {
            "prompt": "Build a todo app",
            "workspace": tmp_path / "workspaces",
            "allowed_actions": [],
            "run_id": "provider-neutral-project",
        })()
    )
    assert result.status == "unavailable"
    assert "LLM_API_KEY" not in (result.error or "")


def test_app_auto_discovers_an_installed_local_model_for_general_chat(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.main.discover_local_model",
        lambda url, **kwargs: "qwen2.5:3b",
    )
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    application = create_app(settings)
    handler = application.state.kernel.router.registry.resolve("general-conversation").handler

    assert handler.runtime.local.backend.model == "qwen2.5:3b"


def test_connected_chatgpt_web_is_primary_when_no_real_local_model_exists(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: None)
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
        chatgpt_web_enabled=True,
        chatgpt_web_bridge_url="http://127.0.0.1:47831",
    )

    application = create_app(settings)
    handler = application.state.kernel.router.registry.resolve("general-conversation").handler

    assert handler.runtime.local is None
    assert handler.runtime.web is not None
