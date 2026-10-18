from __future__ import annotations

from app.capabilities.manager import CapabilityManager, CapabilityStatus


def build_core_capability_manager() -> CapabilityManager:
    """Register only lightweight Core capabilities during idle startup."""

    manager = CapabilityManager()
    manager.register(
        "conversation",
        handler=lambda value: value,
        initial_status=CapabilityStatus.READY,
    )
    manager.register(
        "memory",
        handler=lambda value: value,
        initial_status=CapabilityStatus.READY,
    )
    manager.register(
        "desktop-presence",
        handler=lambda value: value,
        initial_status=CapabilityStatus.READY,
    )
    manager.register("project-execution")
    return manager
