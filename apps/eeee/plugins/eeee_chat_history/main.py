"""Launch the EEEE chat history plugin as its own desktop process."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EEEE chat history plugin")
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--conversation-id", default="desktop-default")
    arguments = parser.parse_args(argv)

    package_root = Path(__file__).resolve().parent
    if __package__ in {None, ""}:
        sys.path.insert(0, str(package_root.parent))
        from eeee_chat_history.window import ChatHistoryWindow
    else:
        from .window import ChatHistoryWindow

    from PySide6.QtWidgets import QApplication

    from app.desktop.client import PetApiClient

    application = QApplication.instance() or QApplication(sys.argv)
    window = ChatHistoryWindow(
        PetApiClient(arguments.api_url, assistant_timeout_seconds=180.0),
        conversation_id=arguments.conversation_id,
    )
    window.show()
    window.raise_()
    window.activateWindow()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
