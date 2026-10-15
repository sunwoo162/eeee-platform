import time

import pytest

from app.capabilities.manager import (
    CapabilityExecution,
    CapabilityManager,
    CapabilityStatus,
    InvalidCapabilityTransition,
    PermissionDenied,
)
from app.capabilities.registry import build_core_capability_manager


def test_core_capabilities_are_ready_without_loading_project_execution():
    manager = build_core_capability_manager()

    assert manager.status("conversation") == CapabilityStatus.READY
    assert manager.status("memory") == CapabilityStatus.READY
    assert manager.status("desktop-presence") == CapabilityStatus.READY
    assert manager.status("project-execution") == CapabilityStatus.NOT_INSTALLED


def test_capability_status_lifecycle_is_explicit():
    manager = CapabilityManager()
    manager.register("calendar", handler=lambda value: {"ok": value})

    assert manager.status("calendar") == CapabilityStatus.NOT_INSTALLED
    manager.install("calendar")
    manager.require_auth("calendar")
    manager.mark_ready("calendar")
    manager.begin("calendar")
    manager.finish("calendar")

    assert manager.status("calendar") == CapabilityStatus.READY
    with pytest.raises(InvalidCapabilityTransition):
        manager.finish("calendar")


def test_permission_denial_is_blocked_and_not_completed():
    manager = CapabilityManager()
    manager.register("mail", handler=lambda value: {"sent": value}, permissions={"mail.send"})
    manager.install("mail")
    manager.mark_ready("mail")

    with pytest.raises(PermissionDenied):
        manager.invoke("mail", {}, granted_permissions=set())

    assert manager.status("mail") == CapabilityStatus.READY


def test_worker_crash_and_timeout_are_isolated_from_core():
    manager = CapabilityManager()
    manager.register("unstable", handler=lambda value: 1 / 0)
    manager.register("slow", handler=lambda value: time.sleep(0.1), timeout_seconds=0.01)
    manager.install("unstable")
    manager.install("slow")
    manager.mark_ready("unstable")
    manager.mark_ready("slow")

    crashed = manager.invoke("unstable", {})
    timed_out = manager.invoke("slow", {})

    assert isinstance(crashed, CapabilityExecution)
    assert crashed.status == CapabilityStatus.FAILED
    assert crashed.error_code == "worker_crash"
    assert timed_out.status == CapabilityStatus.FAILED
    assert timed_out.error_code == "worker_timeout"
    assert manager.status("unstable") == CapabilityStatus.FAILED
    assert manager.status("slow") == CapabilityStatus.FAILED
