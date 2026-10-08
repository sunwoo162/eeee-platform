"""Embedded local API runtime for the desktop pet."""

from __future__ import annotations

import threading
import time
import os
import subprocess
from pathlib import Path

import uvicorn

from app.config import Settings
from app.main import create_app


class ApiStartupError(RuntimeError):
    """Raised when the embedded API cannot become ready."""


class EmbeddedApiRuntime:
    """Run the local FastAPI coordinator in a daemon thread."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        startup_timeout: float = 5.0,
    ) -> None:
        self.settings = settings or Settings()
        self.host = host
        self.port = port
        self.startup_timeout = startup_timeout
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._chatgpt_bridge: subprocess.Popen[str] | None = None

    @property
    def is_running(self) -> bool:
        return bool(
            self._server
            and self._thread
            and self._thread.is_alive()
            and self._server.started
            and not self._server.should_exit
        )

    def start(self) -> str:
        if self.is_running:
            raise RuntimeError("Embedded API is already running")

        self._error = None
        self._start_chatgpt_web_bridge()
        self._server = uvicorn.Server(
            uvicorn.Config(
                create_app(self.settings),
                host=self.host,
                port=self.port,
                log_level="critical",
                access_log=False,
                log_config=None,
            )
        )
        self._thread = threading.Thread(
            target=self._run_server,
            name="desktop-pet-api",
            daemon=True,
        )
        self._thread.start()

        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self._server.started:
                actual_port = self._server.servers[0].sockets[0].getsockname()[1]
                return f"http://{self.host}:{actual_port}"
            if not self._thread.is_alive():
                break
            time.sleep(0.01)

        detail = str(self._error) if self._error else "startup timed out"
        self.stop()
        raise ApiStartupError(f"Embedded API failed to start: {detail}")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=self.startup_timeout)
        if self._chatgpt_bridge is not None:
            self._chatgpt_bridge.terminate()
            try:
                self._chatgpt_bridge.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._chatgpt_bridge.kill()
            self._chatgpt_bridge = None

    def _start_chatgpt_web_bridge(self) -> None:
        if not (self.settings.chatgpt_web_enabled and self.settings.chatgpt_web_autostart):
            return
        if not self.settings.chatgpt_web_profile_root:
            return
        root = Path(__file__).resolve().parents[4]
        script = root / "packages" / "iseol" / "dist" / "chatgpt-web" / "eeee-bridge.js"
        if not script.exists():
            return
        env = os.environ.copy()
        env.update({
            "ISEOL_CHATGPT_WEB_ENABLED": "true",
            "ISEOL_CHATGPT_BROWSER_ENABLED": "true",
            "ISEOL_CHATGPT_BROWSER_PROFILE_ROOT": str(self.settings.chatgpt_web_profile_root),
            "ISEOL_CHATGPT_BROWSER_HEADLESS": str(self.settings.chatgpt_web_headless).lower(),
            "EEEE_CHATGPT_WEB_BRIDGE_PORT": str(self.settings.chatgpt_web_bridge_port),
        })
        if self.settings.chatgpt_web_browser_executable:
            env["ISEOL_CHATGPT_BROWSER_EXECUTABLE"] = self.settings.chatgpt_web_browser_executable
        self._chatgpt_bridge = subprocess.Popen(
            [self.settings.chatgpt_web_node_path, str(script)],
            cwd=str(root / "packages" / "iseol"),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.settings.chatgpt_web_bridge_url = (
            f"http://127.0.0.1:{self.settings.chatgpt_web_bridge_port}"
        )

    def _run_server(self) -> None:
        assert self._server is not None
        try:
            self._server.run()
        except BaseException as exc:  # pragma: no cover - depends on server failure
            self._error = exc
