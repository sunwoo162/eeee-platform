from __future__ import annotations

from typing import Literal


CanonicalCapabilityStatus = Literal[
    "not_installed",
    "installed",
    "auth_required",
    "ready",
    "degraded",
    "running",
    "failed",
    "removed",
]

_LEGACY_PLUGIN_STATUS: dict[str, CanonicalCapabilityStatus] = {
    "available": "not_installed",
    "not_installed": "not_installed",
    "awaiting_authentication": "auth_required",
    "connected": "ready",
    "disabled": "degraded",
    "failed": "failed",
    "installed": "installed",
    "auth_required": "auth_required",
    "ready": "ready",
    "degraded": "degraded",
    "running": "running",
    "removed": "removed",
}


def canonical_plugin_status(value: str) -> CanonicalCapabilityStatus:
    try:
        return _LEGACY_PLUGIN_STATUS[value]
    except KeyError as exc:
        raise ValueError(f"unknown plugin status: {value}") from exc
