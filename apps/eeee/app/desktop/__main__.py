import argparse
import os
import sys
from pathlib import Path

from app.config import Settings
from app.desktop.client import PetApiClient
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

    runtime = EmbeddedApiRuntime(settings=settings)
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
    """Import the desktop Qt surface without starting the window or API."""

    try:
        prepare_qt_runtime()
        from PySide6.QtWidgets import QApplication  # noqa: F401
    except Exception:
        return 1
    return 0


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

    window = PetWindow(client, initial_error=startup_error)
    window.show()
    try:
        return application.exec()
    finally:
        if runtime is not None:
            runtime.stop()


if __name__ == "__main__":
    raise SystemExit(main())
