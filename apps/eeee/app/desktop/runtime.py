"""Embedded local API runtime for the desktop pet."""

from __future__ import annotations

import threading
import time
import os
import json
import re
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import uvicorn

from app.config import Settings
from app.main import create_app


_CHROME_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
)
_NODE_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "nodejs/node.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/nodejs/node.exe",
)
_CHATGPT_BROWSER_HEALTHY_STATUSES = frozenset({
    "ready",
    "auth-required",
    "temporarily-limited",
    "conversation-exhausted",
    "usage-limited",
})


def _background_process_kwargs() -> dict[str, int]:
    """Keep helper processes from creating a console beside the GUI pet."""

    if os.name == "nt":
        return {"creationflags": int(subprocess.CREATE_NO_WINDOW)}
    return {}


def _resolve_browser_executable(configured: str | None) -> str:
    if configured and Path(configured).exists():
        return configured
    discovered = shutil.which(configured or "chrome.exe")
    if discovered:
        return discovered
    for candidate in _CHROME_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return configured or "chrome.exe"


def _resolve_node_executable(configured: str) -> str:
    discovered = shutil.which(configured)
    if discovered:
        return discovered
    for candidate in _NODE_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return configured


def _wait_for_tcp_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _chatgpt_bridge_is_healthy(port: int) -> bool:
    """Detect a bridge left by a previous desktop process before spawning another."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read(4096).decode("utf-8"))
            return (
                isinstance(payload, dict)
                and payload.get("service") == "chatgpt-web-bridge"
                and payload.get("connected") is True
                and payload.get("browserStatus") in _CHATGPT_BROWSER_HEALTHY_STATUSES
            )
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return False


def _chatgpt_bridge_is_stale(port: int) -> bool:
    """Detect an orphaned bridge whose browser session is no longer connected."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read(4096).decode("utf-8"))
            return (
                isinstance(payload, dict)
                and payload.get("service") == "chatgpt-web-bridge"
                and (
                    payload.get("connected") is False
                    or payload.get("browserStatus") not in _CHATGPT_BROWSER_HEALTHY_STATUSES
                )
            )
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return False


def _terminate_port_owner(port: int) -> bool:
    """Terminate a process tree that owns one of EEEE's private loopback ports."""
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        pattern = re.compile(rf"127\.0\.0\.1:{port}\s+\S+\s+LISTENING\s+(\d+)", re.IGNORECASE)
        pids = {match.group(1) for match in pattern.finditer(result.stdout)}
        for pid in pids:
            subprocess.run(
                ["taskkill", "/PID", pid, "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        return bool(pids)
    except OSError:
        return False


def _runtime_debug(message: str) -> None:
    """Write temporary startup diagnostics without requiring a console window."""
    try:
        path = Path(os.environ.get("TEMP", ".")) / "gleave-runtime-debug.log"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


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
        self._chatgpt_browser: subprocess.Popen[str] | None = None
        self._chatgpt_bridge_log = None

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
        self._start_chatgpt_web_bridge(visible=False)
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
        if self._chatgpt_bridge_log is not None:
            self._chatgpt_bridge_log.close()
            self._chatgpt_bridge_log = None
        if self._chatgpt_browser is not None:
            self._chatgpt_browser.terminate()
            try:
                self._chatgpt_browser.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._chatgpt_browser.kill()
            self._chatgpt_browser = None

    def _start_chatgpt_web_bridge(self, *, visible: bool | None = None) -> None:
        _runtime_debug(
            "start "
            f"enabled={self.settings.chatgpt_web_enabled} "
            f"autostart={self.settings.chatgpt_web_autostart} "
            f"profile={self.settings.chatgpt_web_profile_root!s} "
            f"frozen={getattr(sys, 'frozen', False)}"
        )
        if not (self.settings.chatgpt_web_enabled and self.settings.chatgpt_web_autostart):
            _runtime_debug("skip disabled")
            return
        if not self.settings.chatgpt_web_profile_root:
            _runtime_debug("skip no profile")
            return
        if _chatgpt_bridge_is_healthy(self.settings.chatgpt_web_bridge_port):
            self.settings.chatgpt_web_bridge_url = (
                f"http://127.0.0.1:{self.settings.chatgpt_web_bridge_port}"
            )
            _runtime_debug("reuse healthy existing bridge")
            return
        if _chatgpt_bridge_is_stale(self.settings.chatgpt_web_bridge_port):
            _runtime_debug("remove stale existing bridge and browser")
            _terminate_port_owner(self.settings.chatgpt_web_bridge_port)
            _terminate_port_owner(self.settings.chatgpt_web_bridge_port + 1)
            time.sleep(0.2)
        if getattr(sys, "frozen", False):
            root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
            script = root / "chatgpt-runtime" / "chatgpt-web" / "eeee-bridge.js"
        else:
            root = Path(__file__).resolve().parents[4]
            script = root / "packages" / "iseol" / "dist" / "chatgpt-web" / "eeee-bridge.js"
        _runtime_debug(f"script={script} exists={script.exists()}")
        if not script.exists():
            _runtime_debug("skip missing script")
            return
        env = os.environ.copy()
        env.update({
            "ISEOL_CHATGPT_WEB_ENABLED": "true",
            "ISEOL_CHATGPT_BROWSER_ENABLED": "true",
            "ISEOL_CHATGPT_BROWSER_PROFILE_ROOT": str(self.settings.chatgpt_web_profile_root),
            "ISEOL_CHATGPT_BROWSER_HEADLESS": str(self.settings.chatgpt_web_headless).lower(),
            "ISEOL_CHATGPT_BROWSER_CDP_URL": f"http://127.0.0.1:{self.settings.chatgpt_web_bridge_port + 1}",
            "EEEE_CHATGPT_WEB_BRIDGE_PORT": str(self.settings.chatgpt_web_bridge_port),
        })
        if self.settings.chatgpt_web_browser_executable:
            env["ISEOL_CHATGPT_BROWSER_EXECUTABLE"] = self.settings.chatgpt_web_browser_executable
        self._launch_chatgpt_browser(visible=visible)
        cdp_ready = _wait_for_tcp_port("127.0.0.1", self.settings.chatgpt_web_bridge_port + 1)
        _runtime_debug(f"cdp_ready={cdp_ready}")
        if not cdp_ready:
            self.stop()
            return
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self._chatgpt_bridge_log = (self.settings.data_dir / "chatgpt-web-bridge.log").open(
            "a", encoding="utf-8"
        )
        self._chatgpt_bridge = subprocess.Popen(
            [_resolve_node_executable(self.settings.chatgpt_web_node_path), str(script)],
            cwd=str(script.parent),
            env=env,
            stdout=self._chatgpt_bridge_log,
            stderr=subprocess.STDOUT,
            text=True,
            **_background_process_kwargs(),
        )
        _runtime_debug(f"bridge_pid={self._chatgpt_bridge.pid}")
        self.settings.chatgpt_web_bridge_url = (
            f"http://127.0.0.1:{self.settings.chatgpt_web_bridge_port}"
        )
        bridge_ready = _wait_for_tcp_port(
            "127.0.0.1", self.settings.chatgpt_web_bridge_port, timeout=45.0
        )
        if self._chatgpt_bridge.poll() is not None:
            _runtime_debug(f"bridge_exit_code={self._chatgpt_bridge.returncode}")
            bridge_ready = False
        if not bridge_ready:
            _runtime_debug("bridge_ready=false")
            self._chatgpt_bridge.terminate()
            self._chatgpt_bridge = None
            self.settings.chatgpt_web_bridge_url = None
        else:
            _runtime_debug("bridge_ready=true")

    def open_chatgpt_login(self) -> bool:
        """Open the persisted normal-Chrome profile used for ChatGPT login."""

        if not self.settings.chatgpt_web_profile_root:
            return False
        try:
            # Normal operation owns a hidden browser. Replace that session
            # with a visible one only for the explicit one-time login action.
            if self._chatgpt_browser is not None and self._chatgpt_browser.poll() is None:
                if not self.settings.chatgpt_web_headless:
                    return True
                self._stop_chatgpt_session()
            self._start_chatgpt_web_bridge(visible=True)
            return True
        except OSError:
            return False

    def _launch_chatgpt_browser(self, *, visible: bool | None = None) -> None:
        chrome = _resolve_browser_executable(self.settings.chatgpt_web_browser_executable)
        if visible is None:
            visible = not self.settings.chatgpt_web_headless
        command = [
            chrome,
            f"--user-data-dir={self.settings.chatgpt_web_profile_root}",
            f"--remote-debugging-port={self.settings.chatgpt_web_bridge_port + 1}",
            "--remote-allow-origins=*",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            "https://chatgpt.com/",
        ]
        if not visible:
            # The assistant must never cover the user's active window during
            # normal operation. Keep the persisted profile and CDP session,
            # but run Chromium without a desktop window. Explicit login uses
            # the same profile with a visible browser below.
            command.insert(1, "--headless=new")
        self._chatgpt_browser = subprocess.Popen(
            command,
            **_background_process_kwargs(),
        )

    def _stop_chatgpt_session(self) -> None:
        if self._chatgpt_bridge is not None:
            self._chatgpt_bridge.terminate()
            try:
                self._chatgpt_bridge.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._chatgpt_bridge.kill()
            self._chatgpt_bridge = None
        if self._chatgpt_bridge_log is not None:
            self._chatgpt_bridge_log.close()
            self._chatgpt_bridge_log = None
        if self._chatgpt_browser is not None:
            self._chatgpt_browser.terminate()
            try:
                self._chatgpt_browser.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._chatgpt_browser.kill()
            self._chatgpt_browser = None

    def _run_server(self) -> None:
        assert self._server is not None
        try:
            self._server.run()
        except BaseException as exc:  # pragma: no cover - depends on server failure
            self._error = exc
