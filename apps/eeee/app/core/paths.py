from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def default_data_dir(
    app_name: str = "EEEE", *, environment: Mapping[str, str] | None = None
) -> Path:
    """Return the stable per-user data directory used by the local Core."""
    env = environment or os.environ
    local_app_data = env.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / app_name
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / app_name
    data_home = env.get("XDG_DATA_HOME")
    return Path(data_home) / app_name if data_home else Path.home() / ".local" / "share" / app_name
