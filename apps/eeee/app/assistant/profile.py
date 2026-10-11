"""Small local store for EEEE's user-facing assistant profile.

The profile is intentionally local and non-secret.  It is read at request
time so changing the pet in the desktop UI affects the next Web turn without
restarting the application or putting credentials in the prompt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_PROFILE: dict[str, str] = {
    "name": "EEEE",
    "avatar": "🐾",
    "personality": "따뜻하고 세심하며 사용자의 맥락을 오래 기억하는 개인 비서",
    "tone": "친근하고 간결한 한국어",
    "role": "사용자의 일상과 작업을 돕는 개인 비서",
}


def load_profile(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return dict(DEFAULT_PROFILE)
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return dict(DEFAULT_PROFILE)
    if not isinstance(payload, dict):
        return dict(DEFAULT_PROFILE)
    profile = dict(DEFAULT_PROFILE)
    for key in profile:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            profile[key] = value.strip()[:300]
    return profile


def save_profile(path: Path, profile: dict[str, str]) -> dict[str, str]:
    current = load_profile(path)
    for key in current:
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            current[key] = value.strip()[:300]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return current
