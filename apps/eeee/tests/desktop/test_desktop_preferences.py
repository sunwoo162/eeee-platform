from pathlib import Path

from app.config import Settings
from app.desktop.preferences import load_preferences, apply_preferences, save_preferences


def test_first_run_preferences_keep_web_chatgpt_in_the_background(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    preferences = load_preferences()

    assert preferences.chatgpt_web_enabled is True
    assert preferences.chatgpt_web_autostart is False
    assert preferences.profile_root == tmp_path / "Gleave" / "chatgpt-web-profile"


def test_legacy_preferences_do_not_reopen_a_browser_on_startup(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = tmp_path / "Gleave" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"version": 1, "chatgptWebEnabled": true, "chatgptWebAutostart": true}\n',
        encoding="utf-8",
    )

    preferences = load_preferences()

    assert preferences.chatgpt_web_autostart is False


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
