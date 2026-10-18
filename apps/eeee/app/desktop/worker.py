"""Small Qt thread-pool adapter for blocking desktop operations."""

from collections.abc import Callable
from threading import Event


class ConversationWorker:
    """Synchronous Core conversation operation for a background task runner."""

    def __init__(self, client, session) -> None:
        self.client = client
        self.session = session

    def run_turn(self, text: str) -> dict[str, object]:
        request = self.session.submit(text)
        events = list(self.client.stream_request_events(request["requestId"]))
        self.session.apply_events(request, events)
        return {
            "request": request,
            "events": events,
            "state": self.session.state,
            "messages": list(self.session.messages),
        }


class QtTaskRunner:
    """Run blocking callables off the Qt GUI thread and deliver callbacks safely."""

    def __init__(self, *, max_threads: int = 1, parent=None):
        try:
            from PySide6.QtCore import QThreadPool
        except ImportError as exc:
            raise RuntimeError(
                'PySide6 is required for the desktop shell. Install with `pip install -e ".[desktop]"`.'
            ) from exc

        self._pool = QThreadPool(parent)
        self._pool.setMaxThreadCount(max_threads)
        self._tasks = set()
        self._shutting_down = Event()

    def submit(
        self,
        operation: Callable[[], object],
        on_success: Callable[[object], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        from PySide6.QtCore import QObject, QRunnable, Signal

        class _Signals(QObject):
            succeeded = Signal(object)
            failed = Signal(object)

        shutting_down = self._shutting_down

        class _Task(QRunnable):
            def __init__(self):
                super().__init__()
                self.setAutoDelete(False)
                self.signals = _Signals()

            def run(self):
                try:
                    result = operation()
                except Exception as exc:
                    if not shutting_down.is_set():
                        self.signals.failed.emit(exc)
                else:
                    if not shutting_down.is_set():
                        self.signals.succeeded.emit(result)

        task = _Task()
        self._tasks.add(task)

        def handle_success(result):
            try:
                if not self._shutting_down.is_set():
                    on_success(result)
            finally:
                self._tasks.discard(task)

        def handle_error(error):
            try:
                if not self._shutting_down.is_set():
                    on_error(error)
            finally:
                self._tasks.discard(task)

        task.signals.succeeded.connect(handle_success)
        task.signals.failed.connect(handle_error)
        self._pool.start(task)

    def shutdown(self, timeout_ms: int = 2_000) -> None:
        self._shutting_down.set()
        self._pool.clear()
        self._pool.waitForDone(timeout_ms)
