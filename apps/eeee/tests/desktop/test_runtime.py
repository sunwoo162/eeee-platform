import time
import subprocess
from pathlib import Path

import httpx

from app.config import Settings
from app.desktop.__main__ import connect_desktop_api, run_gui_self_test, run_self_test
from app.desktop.runtime import EmbeddedApiRuntime, _resolve_browser_executable


def test_resolves_chrome_from_common_windows_install_path(monkeypatch, tmp_path):
    chrome = tmp_path / "chrome.exe"
    chrome.write_bytes(b"")
    monkeypatch.setattr("app.desktop.runtime.shutil.which", lambda _: None)
    monkeypatch.setattr(
        "app.desktop.runtime._CHROME_CANDIDATES",
        (Path(chrome),),
    )

    assert _resolve_browser_executable(None) == str(chrome)


def test_chatgpt_browser_is_minimized_for_normal_runtime(monkeypatch, tmp_path):
    launched = []
    launch_kwargs = []

    class FakeProcess:
        def poll(self):
            return None

    def fake_popen(args, **kwargs):
        launched.append(args)
        launch_kwargs.append(kwargs)
        return FakeProcess()

    monkeypatch.setattr(
        "app.desktop.runtime._resolve_browser_executable",
        lambda _: "chrome.exe",
    )
    monkeypatch.setattr(
        "app.desktop.runtime.subprocess.Popen",
        fake_popen,
    )
    runtime = EmbeddedApiRuntime(
        settings=Settings(
            data_dir=tmp_path / "data",
            workspace_root=tmp_path / "workspaces",
            chatgpt_web_headless=True,
            chatgpt_web_profile_root=tmp_path / "profile",
        )
    )

    runtime._launch_chatgpt_browser()

    assert "--start-minimized" in launched[0]
    assert "--headless=new" not in launched[0]
    assert launch_kwargs[0]["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_chatgpt_login_browser_is_visible(monkeypatch, tmp_path):
    launched = []

    class FakeProcess:
        def poll(self):
            return None

    monkeypatch.setattr(
        "app.desktop.runtime._resolve_browser_executable",
        lambda _: "chrome.exe",
    )
    monkeypatch.setattr(
        "app.desktop.runtime.subprocess.Popen",
        lambda args, **kwargs: (launched.append(args) or FakeProcess()),
    )
    runtime = EmbeddedApiRuntime(
        settings=Settings(
            data_dir=tmp_path / "data",
            workspace_root=tmp_path / "workspaces",
            chatgpt_web_headless=True,
            chatgpt_web_profile_root=tmp_path / "profile",
        )
    )

    runtime._launch_chatgpt_browser(visible=True)

    assert "--start-minimized" not in launched[0]


def test_embedded_runtime_serves_health_and_stops(tmp_path):
    runtime = EmbeddedApiRuntime(
        settings=Settings(
            data_dir=tmp_path / "data",
            workspace_root=tmp_path / "workspaces",
        )
    )

    base_url = runtime.start()
    try:
        response = httpx.get(f"{base_url}/health", timeout=2.0)

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    finally:
        stop_started = time.monotonic()
        runtime.stop()

    assert runtime.is_running is False
    assert time.monotonic() - stop_started < 1.0


def test_desktop_connection_starts_embedded_api_when_no_url_is_configured(tmp_path):
    client, runtime = connect_desktop_api(
        settings=Settings(
            data_dir=tmp_path / "data",
            workspace_root=tmp_path / "workspaces",
        )
    )

    assert runtime is not None
    try:
        assert client.get_state()["state"] == "idle"
    finally:
        stop_started = time.monotonic()
        runtime.stop()

    assert time.monotonic() - stop_started < 1.0


def test_desktop_connection_uses_explicit_api_url_without_starting_runtime():
    client, runtime = connect_desktop_api("http://example.test:8123")

    assert client.base_url == "http://example.test:8123"
    assert runtime is None


def test_desktop_self_test_starts_and_checks_the_embedded_api(tmp_path):
    result = run_self_test(
        Settings(
            data_dir=tmp_path / "data",
            workspace_root=tmp_path / "workspaces",
        )
    )

    assert result == 0


def test_desktop_gui_self_test_imports_qt_widgets():
    assert run_gui_self_test() == 0
