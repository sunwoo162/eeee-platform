"""User-facing desktop preferences stored outside the repository."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings


@dataclass(frozen=True)
class DesktopPreferences:
    chatgpt_web_enabled: bool
    chatgpt_web_autostart: bool
    profile_root: Path
    browser_executable: str | None = None


def _local_app_data() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    return Path(root) if root else Path.home() / ".local" / "share"


def preferences_path() -> Path:
    return _local_app_data() / "Gleave" / "config.json"


def _defaults() -> DesktopPreferences:
    return DesktopPreferences(
        chatgpt_web_enabled=True,
        chatgpt_web_autostart=True,
        profile_root=_local_app_data() / "Gleave" / "chatgpt-web-profile",
    )


def load_preferences() -> DesktopPreferences:
    defaults = _defaults()
    path = preferences_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return defaults
    if not isinstance(payload, dict):
        return defaults
    profile = payload.get("profileRoot")
    return DesktopPreferences(
        chatgpt_web_enabled=bool(payload.get("chatgptWebEnabled", defaults.chatgpt_web_enabled)),
        chatgpt_web_autostart=bool(payload.get("chatgptWebAutostart", defaults.chatgpt_web_autostart)),
        profile_root=Path(profile) if isinstance(profile, str) and profile.strip() else defaults.profile_root,
        browser_executable=(
            payload["browserExecutable"]
            if isinstance(payload.get("browserExecutable"), str)
            else None
        ),
    )


def save_preferences(
    *,
    chatgpt_web_enabled: bool,
    chatgpt_web_autostart: bool,
    profile_root: Path,
    browser_executable: Path | str | None = None,
) -> None:
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "chatgptWebEnabled": chatgpt_web_enabled,
        "chatgptWebAutostart": chatgpt_web_autostart,
        "profileRoot": str(profile_root),
    }
    if browser_executable:
        payload["browserExecutable"] = str(browser_executable)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_preferences(settings: Settings, preferences: DesktopPreferences) -> Settings:
    settings.chatgpt_web_enabled = preferences.chatgpt_web_enabled
    settings.chatgpt_web_autostart = preferences.chatgpt_web_autostart
    settings.chatgpt_web_profile_root = preferences.profile_root
    settings.chatgpt_web_browser_executable = preferences.browser_executable
    return settings
