import pytest

from app.config import Settings
from fastapi.testclient import TestClient

from app.main import create_app
from app.agent.lazy_runtime import LazyAgentRuntime


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


def test_default_application_defers_optional_runtime_until_project_execution():
    application = create_app()

    assert isinstance(application.state.api_flow.runtime, LazyAgentRuntime)
    assert application.state.api_flow.runtime.loaded is False


def test_execution_settings_require_supported_mode_and_positive_limits():
    with pytest.raises(ValueError):
        Settings(execution_mode="unknown")
    with pytest.raises(ValueError):
        Settings(command_timeout_seconds=0)
    with pytest.raises(ValueError):
        Settings(max_command_output_chars=0)
