from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plugins.connectors import ConnectorConnection, ConnectorHealth
from app.plugins.credentials import MemoryCredentialStore


class _HealthyNotionConnector:
    plugin_id = "notion"

    def connect(self, user_id, credential, approved_permissions):
        return ConnectorConnection(
            user_id=user_id,
            plugin_id=self.plugin_id,
            approved_permissions=frozenset(approved_permissions),
            client=object(),
        )

    def disconnect(self, connection):
        return None

    def health(self, connection):
        return ConnectorHealth(status="healthy", code="healthy", reason="ok")


def test_app_uses_builtin_for_basic_chat_without_external_provider(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: None)
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    with TestClient(create_app(settings)) as client:
        response = client.post("/api/assistant/route", json={"text": "안녕"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["provider"] == "builtin"
    assert "안녕" in payload["message"]
    assert payload["response_verification"]["decision"] == "WARN"
    assert "LLM_API_KEY" not in payload["message"]


def test_connected_plugin_state_flows_into_project_provisioner(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: None)
    application = create_app(Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces"))
    application.state.plugin_platform.credentials = MemoryCredentialStore()
    application.state.plugin_platform.connectors = {"notion": _HealthyNotionConnector()}
    application.state.plugin_platform.install("notion")
    application.state.plugin_platform.connect(
        "local-user", "notion", {"pages.read"}, {"token": "secret"}, "Workspace"
    )

    assert application.state.api_flow.project_provisioner.configured_connector_ids() == {"notion"}


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


def test_app_does_not_wire_discovered_ollama_into_general_chat(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.main.discover_local_model",
        lambda url, **kwargs: "qwen2.5:3b",
    )
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: None)
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    application = create_app(settings)
    handler = application.state.kernel.router.registry.resolve("general-conversation").handler

    assert handler.runtime.local is None


def test_general_chat_does_not_create_a_local_model_even_when_one_is_installed(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: "qwen3:4b")
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: "qwen2.5:1.5b")
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    application = create_app(settings)
    general = application.state.kernel.router.registry.resolve("general-conversation").handler

    assert general.runtime.local is None
    assert application.state.api_flow.runtime.__class__.__name__ == "HybridAssistantRuntime"


def test_general_chat_uses_web_when_project_runtime_is_injected(monkeypatch, tmp_path):
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

    assert general.runtime.local is None
    assert general.runtime.web is not None


def test_general_route_uses_builtin_instead_of_discovered_local_provider(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: "qwen3:4b")
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: "qwen2.5:1.5b")
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")

    application = create_app(settings)

    from fastapi.testclient import TestClient

    with TestClient(application) as client:
        response = client.post("/api/assistant/route", json={"text": "안녕"})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["provider"] == "builtin"


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


def test_explicit_provider_config_is_wired_into_plugin_platform_and_oauth(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: None)
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
        claim_latch_auto_start=False,
        plugin_provider_config_json=(
            '{"gmail": {"baseUrl": "https://gmail.example", "oauth": {'
            '"authorizationEndpoint": "https://accounts.example/authorize", '
            '"tokenEndpoint": "https://accounts.example/token", '
            '"clientId": "public-client", "scopes": ["mail.read"]}}}'
        ),
    )

    application = create_app(settings)

    assert set(application.state.plugin_platform.connectors) == {"notion", "gmail"}
    assert application.state.oauth_configs["gmail"].client_id == "public-client"
    assert application.state.plugin_platform.status("gmail") == "not_installed"


def test_gmail_builtin_profile_is_wired_from_operator_settings(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: None)
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
        claim_latch_auto_start=False,
        gmail_oauth_client_id="gmail-client",
        gmail_oauth_client_secret="gmail-secret",
    )

    application = create_app(settings)

    assert set(application.state.plugin_platform.connectors) == {"notion", "gmail"}
    assert application.state.oauth_configs["gmail"].client_id == "gmail-client"
    assert application.state.oauth_configs["gmail"].client_secret == "gmail-secret"


def test_invalid_provider_config_fails_during_app_creation(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: None)
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
        claim_latch_auto_start=False,
        plugin_provider_config_json="not-json",
    )

    import pytest

    with pytest.raises(ValueError, match="invalid JSON"):
        create_app(settings)
