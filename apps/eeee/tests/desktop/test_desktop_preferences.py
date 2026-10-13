from pathlib import Path

from app.config import Settings
from app.desktop.preferences import load_preferences, apply_preferences, save_preferences


def test_first_run_preferences_reconnect_web_chatgpt_in_the_background(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    preferences = load_preferences()

    assert preferences.chatgpt_web_enabled is True
    assert preferences.chatgpt_web_autostart is True
    assert preferences.profile_root == tmp_path / "Gleave" / "chatgpt-web-profile"


def test_legacy_preferences_reconnect_without_showing_a_browser_window(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = tmp_path / "Gleave" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"version": 1, "chatgptWebEnabled": true, "chatgptWebAutostart": true}\n',
        encoding="utf-8",
    )

    preferences = load_preferences()

    assert preferences.chatgpt_web_autostart is True


def test_preferences_round_trip_and_apply_to_desktop_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_preferences(
        chatgpt_web_enabled=True,
        chatgpt_web_autostart=True,
        profile_root=tmp_path / "custom-profile",
        browser_executable=Path("C:/custom/chrome.exe"),
    )

    preferences = load_preferences()
    settings = Settings()
    apply_preferences(settings, preferences)

    assert preferences.chatgpt_web_enabled is True
    assert settings.chatgpt_web_enabled is True
    assert settings.chatgpt_web_autostart is True
    assert settings.chatgpt_web_profile_root == tmp_path / "custom-profile"
    assert Path(settings.chatgpt_web_browser_executable) == Path("C:/custom/chrome.exe")

    payload = (tmp_path / "Gleave" / "config.json").read_text(encoding="utf-8")
    assert '"chatgptWebEnabled": true' in payload
    assert '"chatgptWebAutostart": true' in payload
    assert '"profileRoot": "' in payload
