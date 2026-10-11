import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from app.desktop.client import PetApiClient
from app.desktop.window import PetWindow


def test_desktop_companion_is_an_interactive_always_on_top_widget():
    app = QApplication.instance() or QApplication([])
    window = PetWindow(PetApiClient("http://127.0.0.1:1"))
    try:
        assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert hasattr(window, "hide_to_tray")
        assert hasattr(window, "restore_from_tray")
        assert hasattr(window, "request_quit")
        assert hasattr(window, "assistant_input")
        assert hasattr(window, "assistant_button")
        assert hasattr(window, "trust_status")
        assert hasattr(window, "pairing_button")
        assert hasattr(window, "events_view")

        window.show()
        window.hide_to_tray()
        assert not window.isVisible()
        window.restore_from_tray()
        assert window.isVisible()
    finally:
        window.request_quit()
        window.close()
        app.processEvents()


def test_desktop_companion_is_a_calm_launcher_with_korean_default_and_english_option():
    app = QApplication.instance() or QApplication([])
    settings = QSettings("Gleave", "GleaveDesktop")
    previous_language = settings.value("language", None)
    settings.setValue("language", "ko")
    window = PetWindow(PetApiClient("http://127.0.0.1:1"))
    try:
        assert window.objectName() == "desktopCompanion"
        assert "QWidget {" not in window.styleSheet()
        assert "#desktopCompanion" in window.styleSheet()
        assert window.language_select.currentData() == "ko"
        assert window.language_select.count() == 2
        assert window.workspace_button.text() == "Gleave 워크스페이스 열기"

        window.show()
        app.processEvents()
        assert not window.legacy_panel.isVisible()

        window._open_workspace()
        assert window._workspace is not None
        assert window._workspace.windowTitle() == "EEEE Workspace"

        window.language_select.setCurrentIndex(1)
        app.processEvents()
        assert window.language_select.currentData() == "en"
        assert window.workspace_button.text() == "Open Gleave workspace"
        window._open_workspace()
        assert window._workspace is not None
    finally:
        window.request_quit()
        window.close()
        app.processEvents()
        if previous_language is None:
            settings.remove("language")
        else:
            settings.setValue("language", previous_language)
