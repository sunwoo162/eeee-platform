from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Any, Callable


class CapabilityStatus(StrEnum):
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"
    AUTH_REQUIRED = "auth_required"
    READY = "ready"
    DEGRADED = "degraded"
    RUNNING = "running"
    FAILED = "failed"
    REMOVED = "removed"


class InvalidCapabilityTransition(ValueError):
    pass


class PermissionDenied(PermissionError):
    pass


@dataclass(frozen=True)
class CapabilityExecution:
    capability_id: str
    status: CapabilityStatus
    output: dict[str, object] | None = None
    error_code: str | None = None
    message: str | None = None


@dataclass
class _Capability:
    capability_id: str
    handler: Callable[[dict[str, object]], Any] | None
    permissions: frozenset[str]
    timeout_seconds: float
    status: CapabilityStatus


_TRANSITIONS: dict[CapabilityStatus, frozenset[CapabilityStatus]] = {
    CapabilityStatus.NOT_INSTALLED: frozenset({CapabilityStatus.INSTALLED}),
    CapabilityStatus.INSTALLED: frozenset({
        CapabilityStatus.AUTH_REQUIRED,
        CapabilityStatus.READY,
        CapabilityStatus.REMOVED,
    }),
    CapabilityStatus.AUTH_REQUIRED: frozenset({
        CapabilityStatus.READY,
        CapabilityStatus.DEGRADED,
        CapabilityStatus.REMOVED,
    }),
    CapabilityStatus.READY: frozenset({CapabilityStatus.RUNNING, CapabilityStatus.REMOVED}),
    CapabilityStatus.DEGRADED: frozenset({CapabilityStatus.READY, CapabilityStatus.FAILED, CapabilityStatus.REMOVED}),
    CapabilityStatus.RUNNING: frozenset({CapabilityStatus.READY, CapabilityStatus.FAILED, CapabilityStatus.DEGRADED}),
    CapabilityStatus.FAILED: frozenset({CapabilityStatus.INSTALLED, CapabilityStatus.READY, CapabilityStatus.REMOVED}),
    CapabilityStatus.REMOVED: frozenset({CapabilityStatus.NOT_INSTALLED}),
}


class CapabilityManager:
    """Keep optional capabilities isolated from Core's conversation loop."""

    def __init__(self) -> None:
        self._capabilities: dict[str, _Capability] = {}
        self._lock = RLock()

    def register(
        self,
        capability_id: str,
        *,
        handler: Callable[[dict[str, object]], Any] | None = None,
        permissions: set[str] | frozenset[str] | None = None,
        timeout_seconds: float = 30.0,
        initial_status: CapabilityStatus = CapabilityStatus.NOT_INSTALLED,
    ) -> None:
        if not capability_id.strip():
            raise ValueError("capability_id is required")
        if capability_id in self._capabilities:
            raise ValueError(f"capability already registered: {capability_id}")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._capabilities[capability_id] = _Capability(
            capability_id,
            handler,
            frozenset(permissions or set()),
            timeout_seconds,
            initial_status,
        )

    def status(self, capability_id: str) -> CapabilityStatus:
        return self._get(capability_id).status

    def snapshot(self) -> dict[str, str]:
        return {capability_id: capability.status.value for capability_id, capability in self._capabilities.items()}

    def install(self, capability_id: str) -> None:
        self._transition(capability_id, CapabilityStatus.INSTALLED)

    def require_auth(self, capability_id: str) -> None:
        self._transition(capability_id, CapabilityStatus.AUTH_REQUIRED)

    def mark_ready(self, capability_id: str) -> None:
        current = self.status(capability_id)
        if current == CapabilityStatus.NOT_INSTALLED:
            self.install(capability_id)
            current = self.status(capability_id)
        if current == CapabilityStatus.INSTALLED or current == CapabilityStatus.AUTH_REQUIRED or current == CapabilityStatus.DEGRADED or current == CapabilityStatus.FAILED:
            self._transition(capability_id, CapabilityStatus.READY)
        elif current != CapabilityStatus.READY:
            raise InvalidCapabilityTransition(f"Cannot mark {current} capability ready")

    def begin(self, capability_id: str) -> None:
        self._transition(capability_id, CapabilityStatus.RUNNING)

    def finish(self, capability_id: str) -> None:
        self._transition(capability_id, CapabilityStatus.READY)

    def invoke(
        self,
        capability_id: str,
        value: dict[str, object],
        *,
        granted_permissions: set[str] | frozenset[str] | None = None,
    ) -> CapabilityExecution:
        capability = self._get(capability_id)
        if capability.status != CapabilityStatus.READY:
            return CapabilityExecution(
                capability_id,
                capability.status,
                error_code="capability_not_ready",
                message=f"Capability is {capability.status.value}",
            )
        missing = capability.permissions - frozenset(granted_permissions or set())
        if missing:
            raise PermissionDenied(f"Missing capability permissions: {sorted(missing)}")
        self.begin(capability_id)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"eeee-capability-{capability_id}")
        try:
            if capability.handler is None:
                self._fail(capability_id)
                return CapabilityExecution(capability_id, CapabilityStatus.FAILED, error_code="worker_missing")
            future = executor.submit(capability.handler, value)
            try:
                output = future.result(timeout=capability.timeout_seconds)
            except TimeoutError:
                future.cancel()
                self._fail(capability_id)
                return CapabilityExecution(capability_id, CapabilityStatus.FAILED, error_code="worker_timeout")
            except Exception as exc:
                self._fail(capability_id)
                return CapabilityExecution(
                    capability_id,
                    CapabilityStatus.FAILED,
                    error_code="worker_crash",
                    message=str(exc) or type(exc).__name__,
                )
            self.finish(capability_id)
            normalized = output if isinstance(output, dict) else {"value": output}
            return CapabilityExecution(capability_id, CapabilityStatus.READY, output=normalized)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _get(self, capability_id: str) -> _Capability:
        try:
            return self._capabilities[capability_id]
        except KeyError as exc:
            raise KeyError(f"Unknown capability: {capability_id}") from exc

    def _transition(self, capability_id: str, target: CapabilityStatus) -> None:
        with self._lock:
            capability = self._get(capability_id)
            if target not in _TRANSITIONS.get(capability.status, frozenset()):
                raise InvalidCapabilityTransition(
                    f"Cannot transition capability {capability_id} from "
                    f"{capability.status.value} to {target.value}"
                )
            capability.status = target

    def _fail(self, capability_id: str) -> None:
        self._transition(capability_id, CapabilityStatus.FAILED)
