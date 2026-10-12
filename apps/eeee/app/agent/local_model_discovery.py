"""Best-effort discovery for an already-installed local Ollama model."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

import httpx


def _model_score(name: str, index: int) -> tuple[int, int]:
    """Prefer a capable general chat model while keeping discovery stable.

    An explicit ``local_model`` setting still wins in ``main.py``. This score
    only applies when EEEE discovers an already-installed model. Small legacy
    models can answer greetings, but they become unreliable once EEEE adds
    memory context; newer general-purpose models are a safer default.
    """

    normalized = name.casefold()
    score = 0
    if normalized.startswith("qwen3"):
        score += 30
    elif normalized.startswith("qwen2.5"):
        score += 20
    elif normalized.startswith("llama3") or normalized.startswith("mistral"):
        score += 15
    if "coder" in normalized or "code" in normalized:
        score -= 20
    return score, -index


def _fast_model_score(name: str, index: int) -> tuple[int, int]:
    """Prefer a small, responsive model for EEEE's ordinary chat lane."""

    normalized = name.casefold()
    score = 0
    if normalized.startswith("qwen2.5"):
        score += 30
    elif normalized.startswith("llama3") or normalized.startswith("mistral"):
        score += 20
    elif normalized.startswith("qwen3"):
        score += 10
    if "coder" in normalized or "code" in normalized:
        score -= 20
    # Prefer the smaller parameter suffix when models share a family.
    size_match = re.search(r":(\d+(?:\.\d+)?)([bm])(?:$|[-:])", normalized)
    if size_match:
        size = float(size_match.group(1))
        if size_match.group(2) == "m":
            size /= 1000
        score -= int(size * 2)
    return score, -index


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
    candidates: list[tuple[str, int]] = []
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            continue
        name = model.get("name")
        if isinstance(name, str) and name.strip():
            candidates.append((name.strip(), index))
    if candidates:
        return max(candidates, key=lambda item: _model_score(item[0], item[1]))[0]
    return None


def discover_fast_local_model(chat_url: str, *, timeout_seconds: float = 0.5) -> str | None:
    """Return the best responsive local model for casual conversation."""

    try:
        response = httpx.request("GET", _tags_url(chat_url), timeout=timeout_seconds)
        if response.is_error:
            return None
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None
    candidates: list[tuple[str, int]] = []
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            continue
        name = model.get("name")
        if isinstance(name, str) and name.strip():
            candidates.append((name.strip(), index))
    if candidates:
        return max(candidates, key=lambda item: _fast_model_score(item[0], item[1]))[0]
    return None
