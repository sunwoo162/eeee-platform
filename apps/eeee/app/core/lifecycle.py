from __future__ import annotations

from enum import StrEnum

from app.conversations.service import ConversationService
from app.core.lock import ProcessLock
from app.core.recovery import recover_interrupted
from app.storage.sqlite import SQLiteStore


class CoreLifecycleState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DRAINING = "draining"


class CoreLifecycle:
    """Own Core startup/shutdown ordering around one data directory."""

    def __init__(
        self,
        store: SQLiteStore,
        conversation_service: ConversationService,
        *,
        lock: ProcessLock,
    ) -> None:
        self.store = store
        self.conversation_service = conversation_service
        self.lock = lock
        self._state = CoreLifecycleState.STOPPED
        self.recovered_request_ids: list[str] = []

    @property
    def state(self) -> CoreLifecycleState:
        return self._state

    @property
    def accepting_requests(self) -> bool:
        return self._state == CoreLifecycleState.RUNNING

    def start(self) -> None:
        if self._state == CoreLifecycleState.RUNNING:
            return
        self._state = CoreLifecycleState.STARTING
        try:
            self.lock.acquire()
            self.store.init()
            self.recovered_request_ids = recover_interrupted(
                self.conversation_service.store
            )
            self.conversation_service.set_accepting(True)
            self._state = CoreLifecycleState.RUNNING
        except BaseException:
            self.lock.release()
            self._state = CoreLifecycleState.STOPPED
            raise

    def stop(self) -> None:
        if self._state == CoreLifecycleState.STOPPED:
            return
        self._state = CoreLifecycleState.DRAINING
        try:
            self.conversation_service.shutdown()
        finally:
            self.lock.release()
            self._state = CoreLifecycleState.STOPPED
