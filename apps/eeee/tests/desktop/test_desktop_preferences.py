from pathlib import Path

from app.config import Settings
from app.desktop.preferences import load_preferences, apply_preferences, save_preferences


def test_first_run_preferences_enable_chatgpt_without_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    preferences = load_preferences()

    assert preferences.chatgpt_web_enabled is True
    assert preferences.chatgpt_web_autostart is True
    assert preferences.profile_root == tmp_path / "Gleave" / "chatgpt-web-profile"


def test_preferences_round_trip_and_apply_to_desktop_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_preferences(
        chatgpt_web_enabled=False,
        chatgpt_web_autostart=False,
        profile_root=tmp_path / "custom-profile",
        browser_executable=Path("C:/custom/chrome.exe"),
    )

    preferences = load_preferences()
    settings = Settings()
    apply_preferences(settings, preferences)

    assert preferences.chatgpt_web_enabled is False
    assert settings.chatgpt_web_enabled is False
    assert settings.chatgpt_web_autostart is False
    assert settings.chatgpt_web_profile_root == tmp_path / "custom-profile"
    assert Path(settings.chatgpt_web_browser_executable) == Path("C:/custom/chrome.exe")
