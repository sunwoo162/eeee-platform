from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_app_reports_unavailable_instead_of_faking_general_chat(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: None)
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
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: None)
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
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: None)
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    application = create_app(settings)
    handler = application.state.kernel.router.registry.resolve("general-conversation").handler

    assert handler.runtime.local.backend.model == "qwen2.5:3b"


def test_general_chat_can_use_a_fast_model_without_changing_project_model(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: "qwen3:4b")
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: "qwen2.5:1.5b")
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    application = create_app(settings)
    general = application.state.kernel.router.registry.resolve("general-conversation").handler

    assert general.runtime.local.backend.model == "qwen2.5:1.5b"
    assert application.state.api_flow.runtime.backend.model == "qwen3:4b"


def test_general_chat_stays_local_when_project_runtime_is_injected(monkeypatch, tmp_path):
    """A configured ISEOL/project runtime must not hijack ordinary chat."""
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: "qwen3:4b")
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: "qwen2.5:1.5b")
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
        chatgpt_web_enabled=True,
        chatgpt_web_bridge_url="http://127.0.0.1:47831",
    )

    class ProjectRuntime:
        def run(self, request):
            raise AssertionError("project runtime must not handle general conversation")

    application = create_app(settings, agent_runtime=ProjectRuntime())
    general = application.state.kernel.router.registry.resolve("general-conversation").handler

    assert general.runtime.local.backend.model == "qwen2.5:1.5b"
    assert general.runtime.web is not None


def test_general_route_exposes_local_provider(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: "qwen3:4b")
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: "qwen2.5:1.5b")
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    class ConversationRuntime:
        def run(self, request):
            from app.agent.protocol import AgentResult

            return AgentResult(
                status="completed",
                summary="로컬 응답",
                events=[{"type": "local.conversation", "provider": "ollama"}],
                changed_files=[], test_commands=[], error=None,
            )

    application = create_app(settings)
    handler = application.state.kernel.router.registry.resolve("general-conversation").handler
    handler.runtime.local = ConversationRuntime()

    from fastapi.testclient import TestClient

    with TestClient(application) as client:
        response = client.post("/api/assistant/route", json={"text": "안녕"})

    assert response.status_code == 200
    assert response.json()["provider"] == "local"


def test_connected_chatgpt_web_is_primary_when_no_real_local_model_exists(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: None)
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
