"""Standalone entrypoint for the optional EEEE chat history window."""

from __future__ import annotations

import argparse
from typing import Any

import httpx

try:
    from .window import ChatHistoryWindow
except ImportError:  # Direct execution from the installed plugin directory.
    from window import ChatHistoryWindow


class CoreApiClient:
    """Small client kept inside the plugin so the plugin has no core import dependency."""

    def __init__(self, base_url: str, *, timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = httpx.request(method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise RuntimeError(str(detail))
        return response.json() if response.status_code != 204 else {}

    def get_conversations(self, *, query: str = "", limit: int = 50) -> list[dict[str, object]]:
        result = self._request(
            "GET", "/api/assistant/conversations", params={"query": query, "limit": limit}
        )
        if not isinstance(result, list):
            raise RuntimeError("Core returned an invalid conversation list")
        return [item for item in result if isinstance(item, dict)]

    def get_conversation(
        self,
        conversation_id: str = "desktop-default",
        *,
        limit: int = 100,
        before_id: int | None = None,
    ) -> dict[str, object]:
        if not conversation_id or "/" in conversation_id or "\\" in conversation_id:
            raise ValueError("conversation_id must be a path-safe value")
        params: dict[str, object] = {"limit": limit}
        if before_id is not None:
            params["beforeId"] = before_id
        result = self._request("GET", f"/api/assistant/conversations/{conversation_id}", params=params)
        if not isinstance(result, dict):
            raise RuntimeError("Core returned an invalid conversation")
        return result

    def send_conversation_message(
        self, text: str, *, conversation_id: str = "desktop-default"
    ) -> dict[str, object]:
        result = self._request(
            "POST",
            "/api/assistant/route",
            json={"text": text, "conversationId": conversation_id},
        )
        if not isinstance(result, dict):
            raise RuntimeError("Core returned an invalid assistant response")
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EEEE chat history plugin")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--conversation-id", default="desktop-default")
    args = parser.parse_args(argv)

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    window = ChatHistoryWindow(CoreApiClient(args.api_url), conversation_id=args.conversation_id)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
