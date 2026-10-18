import pytest

from app.config import Settings
from fastapi.testclient import TestClient

from app.main import create_app
from app.agent.hybrid_runtime import HybridAssistantRuntime


def test_health_returns_ok():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "claimLatch": {
            "status": "configured",
            "mode": "advisory",
            "profileVersion": "claimlatch-v0.2.0",
            "engineVersion": "0.3.86",
        },
    }


def test_default_application_has_no_ollama_runtime_without_explicit_opt_in(monkeypatch):
    monkeypatch.setattr("app.main.discover_local_model", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.discover_fast_local_model", lambda *args, **kwargs: None)
    application = create_app()

    assert isinstance(application.state.api_flow.runtime, HybridAssistantRuntime)
    assert application.state.api_flow.runtime.local is None
    assert application.state.api_flow.runtime.web is None


def test_execution_settings_require_supported_mode_and_positive_limits():
    with pytest.raises(ValueError):
        Settings(execution_mode="unknown")
    with pytest.raises(ValueError):
        Settings(command_timeout_seconds=0)
    with pytest.raises(ValueError):
        Settings(max_command_output_chars=0)
