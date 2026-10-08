import argparse
from datetime import datetime
import os
import sys
from pathlib import Path

from app.config import Settings
from app.desktop.client import PetApiClient
from app.desktop.preferences import apply_preferences, load_preferences, save_preferences
from app.desktop.runtime import ApiStartupError, EmbeddedApiRuntime


def prepare_qt_runtime() -> None:
    """Make bundled Qt/Shiboken DLLs discoverable before importing QtWidgets."""

    if not getattr(sys, "frozen", False):
        return
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for candidate in (bundle_root / "PySide6", bundle_root / "shiboken6", bundle_root):
        if candidate.is_dir():
            os.add_dll_directory(str(candidate))


def connect_desktop_api(
    api_url: str | None = None,
    *,
    settings: Settings | None = None,
) -> tuple[PetApiClient, EmbeddedApiRuntime | None]:
    configured_url = os.getenv("PET_API_URL") if api_url is None else api_url
    project_id = os.getenv("PET_PROJECT_ID", "default")
    if configured_url:
        return PetApiClient(configured_url, project_id), None

    desktop_settings = settings or Settings()
    preferences = load_preferences()
    apply_preferences(desktop_settings, preferences)
    if not settings:
        save_preferences(
            chatgpt_web_enabled=preferences.chatgpt_web_enabled,
            chatgpt_web_autostart=preferences.chatgpt_web_autostart,
            profile_root=preferences.profile_root,
            browser_executable=preferences.browser_executable,
        )
    runtime = EmbeddedApiRuntime(settings=desktop_settings)
    try:
        return PetApiClient(runtime.start(), project_id), runtime
    except Exception:
        runtime.stop()
        raise


def run_self_test(settings: Settings | None = None) -> int:
    """Start the embedded runtime, verify health, and exit without opening Qt."""

    runtime = EmbeddedApiRuntime(settings=settings)
    try:
        client = PetApiClient(runtime.start(), os.getenv("PET_PROJECT_ID", "default"))
        return 0 if client.get_health().get("status") == "ok" else 1
    except Exception:
        return 1
    finally:
        runtime.stop()


def run_gui_self_test() -> int:
    """Exercise the real Qt surface, including Enter-to-route, without networking."""

    try:
        prepare_qt_runtime()
        from PySide6.QtCore import QEventLoop
        from PySide6.QtWidgets import QApplication
        from app.desktop.window import PetWindow

        class SelfTestClient:
            def __init__(self):
                self.routed_text = None

            def get_state(self):
                return {"state": "idle", "message": "Ready for a development request"}

            def get_desktop_state(self, project_id=None):
                return {"state": "idle", "message": "Ready for a development request"}

            def route_assistant(self, text, workspace=None):
                self.routed_text = text
                return {"status": "completed", "message": "GUI self-test response"}

        application = QApplication.instance() or QApplication([])
        client = SelfTestClient()
        window = PetWindow(client)
        initial_deadline = datetime.now().timestamp() + 3
        while window._busy and datetime.now().timestamp() < initial_deadline:
            application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        window.show_command_surface()
        window.assistant_input.setText("GUI self-test")
        window.assistant_input.returnPressed.emit()
        deadline = datetime.now().timestamp() + 3
        while (
            client.routed_text != "GUI self-test"
            or window.current_state.get("state") != "completed"
        ) and datetime.now().timestamp() < deadline:
            application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        passed = (
            client.routed_text == "GUI self-test"
            and window.current_state.get("state") == "completed"
            and window.detail.text() == "GUI self-test response"
        )
        window.request_quit()
        window.close()
        application.processEvents()
        return 0 if passed else 1
    except Exception:
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gleave Desktop")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="start the embedded API, verify /health, and exit",
    )
    parser.add_argument(
        "--gui-self-test",
        action="store_true",
        help="import the Qt desktop surface and exit",
    )
    arguments = parser.parse_args(argv)
    if arguments.self_test:
        return run_self_test()
    if arguments.gui_self_test:
        return run_gui_self_test()

    prepare_qt_runtime()
    from PySide6.QtWidgets import QApplication

    from app.desktop.window import PetWindow

    application = QApplication([])
    runtime = None
    startup_error = None
    try:
        client, runtime = connect_desktop_api()
    except ApiStartupError as exc:
        client = PetApiClient("http://127.0.0.1:1")
        startup_error = str(exc)

    window = PetWindow(
        client,
        initial_error=startup_error,
        on_open_chatgpt=runtime.open_chatgpt_login if runtime is not None else None,
    )
    window.show()
    try:
        return application.exec()
    finally:
        if runtime is not None:
            runtime.stop()


if __name__ == "__main__":
    raise SystemExit(main())
