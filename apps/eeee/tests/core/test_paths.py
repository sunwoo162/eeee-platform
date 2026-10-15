from pathlib import Path

from app.config import Settings
from app.core.paths import default_data_dir


def test_default_data_dir_uses_local_app_data_on_windows(monkeypatch, tmp_path: Path) -> None:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    assert default_data_dir() == local_app_data / "EEEE"


def test_settings_exposes_ollama_defaults_and_accepts_eeee_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EEEE_OLLAMA_BASE_URL", "http://ollama.local:11434")
    monkeypatch.setenv("EEEE_OLLAMA_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("EEEE_DATA_DIR", str(tmp_path / "data"))

    settings = Settings()

    assert settings.data_dir == tmp_path / "data"
    assert settings.conversation_provider == "auto"
    assert settings.ollama_base_url == "http://ollama.local:11434"
    assert settings.ollama_model == "qwen2.5:7b"


def test_ollama_timeouts_and_context_limit_must_be_positive() -> None:
    for field in ("ollama_connect_timeout_seconds", "ollama_generation_timeout_seconds"):
        try:
            Settings(**{field: 0})
        except ValueError:
            pass
        else:
            raise AssertionError(f"{field} accepted zero")

    try:
        Settings(ollama_context_tokens=0)
    except ValueError:
        pass
    else:
        raise AssertionError("ollama_context_tokens accepted zero")
