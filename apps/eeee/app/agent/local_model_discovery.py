"""Best-effort discovery for an already-installed local Ollama model."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import httpx


def _tags_url(chat_url: str) -> str:
    parsed = urlsplit(chat_url.rstrip("/"))
    path = parsed.path
    if path.endswith("/api/chat"):
        path = path[: -len("/api/chat")] + "/api/tags"
    else:
        path = "/api/tags"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def discover_local_model(chat_url: str, *, timeout_seconds: float = 0.5) -> str | None:
    """Return the first usable locally installed model, or ``None`` quickly.

    Discovery must never delay Desktop startup or turn an unavailable local
    provider into an error. The configured model still takes precedence in
    the application wiring; this helper only fills an empty configuration.
    """

    try:
        response = httpx.request(
            "GET", _tags_url(chat_url), timeout=timeout_seconds
        )
        if response.is_error:
            return None
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None
    for model in models:
        if not isinstance(model, dict):
            continue
        name = model.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None
