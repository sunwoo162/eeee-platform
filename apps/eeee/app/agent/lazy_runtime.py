from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from typing import Any


class LazyAgentRuntime:
    """Construct an optional project runtime only when a run is actually chosen."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._runtime: Any | None = None
        self._lock = Lock()

    @property
    def loaded(self) -> bool:
        return self._runtime is not None

    def run(self, request):
        return self._get().run(request)

    def _get(self):
        if self._runtime is None:
            with self._lock:
                if self._runtime is None:
                    self._runtime = self._factory()
        return self._runtime
