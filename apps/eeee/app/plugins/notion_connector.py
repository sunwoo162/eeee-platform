"""Notion connector adapter around the existing typed REST client."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from app.integrations.notion_client import NotionClient, NotionClientError
from app.plugins.connectors import ConnectorConnection, ConnectorHealth
from app.project_runtime.models import ProjectProfile


class NotionConnector:
    plugin_id = "notion"
    READ_SCOPE = "pages.read"
    WRITE_SCOPE = "pages.write"

    def __init__(self, *, client_factory: Callable[[Mapping[str, str]], NotionClient] | None = None) -> None:
        self.client_factory = client_factory or self._default_factory

    def connect(
        self, user_id: str, credential: Mapping[str, str], approved_permissions: set[str]
    ) -> ConnectorConnection:
        if self.READ_SCOPE not in approved_permissions:
            raise PermissionError(f"{self.READ_SCOPE} approval is required")
        if not approved_permissions.issubset({self.READ_SCOPE, self.WRITE_SCOPE}):
            raise PermissionError("unknown Notion permission scope")
        client = self.client_factory(credential)
        return ConnectorConnection(
            user_id=user_id, plugin_id=self.plugin_id,
            approved_permissions=frozenset(approved_permissions), client=client,
        )

    def disconnect(self, connection: ConnectorConnection) -> None:
        close = getattr(connection.client, "close", None)
        if callable(close):
            close()

    def health(self, connection: ConnectorConnection) -> ConnectorHealth:
        try:
            connection.client.get_page(connection.client.parent_page_id)
        except NotionClientError as exc:
            return self._provider_error(exc)
        except Exception as exc:
            return ConnectorHealth(status="unavailable", code="provider_unavailable", reason="Notion health check failed")
        return ConnectorHealth(status="healthy", code="healthy", reason="Notion connection is healthy")

    def invoke(
        self, connection: ConnectorConnection, action: str, value: dict[str, object]
    ) -> dict[str, object]:
        if action == "get_page":
            self._require(connection, self.READ_SCOPE)
            page_id = value.get("pageId")
            if not isinstance(page_id, str) or not page_id.strip():
                raise ValueError("pageId is required")
            page = connection.client.get_page(page_id)
            return {"id": page.id, "url": page.url}
        if action == "create_project_page":
            self._require(connection, self.WRITE_SCOPE)
            profile = ProjectProfile.model_validate(value.get("profile", {}))
            lines = value.get("lines", [])
            if not isinstance(lines, list) or any(not isinstance(line, str) for line in lines):
                raise ValueError("lines must be a list of strings")
            page = connection.client.create_project_page(profile, lines)
            return {"id": page.id, "url": page.url}
        if action == "append_revision":
            self._require(connection, self.WRITE_SCOPE)
            page_id = value.get("pageId")
            revision = value.get("revision")
            lines = value.get("lines", [])
            if not isinstance(page_id, str) or not page_id.strip() or not isinstance(revision, str):
                raise ValueError("pageId and revision are required")
            if not isinstance(lines, list) or any(not isinstance(line, str) for line in lines):
                raise ValueError("lines must be a list of strings")
            connection.client.append_revision(page_id, revision, lines)
            return {"status": "completed"}
        raise ValueError(f"unknown Notion action: {action}")

    @staticmethod
    def _default_factory(credential: Mapping[str, str]) -> NotionClient:
        token = credential.get("token")
        parent_page_id = credential.get("parentPageId")
        if not isinstance(token, str) or not isinstance(parent_page_id, str):
            raise ValueError("Notion token and parentPageId are required")
        return NotionClient(token, parent_page_id=parent_page_id)

    @staticmethod
    def _require(connection: ConnectorConnection, scope: str) -> None:
        if scope not in connection.approved_permissions:
            raise PermissionError(f"{scope} approval is required")

    @staticmethod
    def _provider_error(error: NotionClientError) -> ConnectorHealth:
        match = re.search(r"\((\d{3})\)", str(error))
        status_code = int(match.group(1)) if match else 0
        if status_code == 401:
            return ConnectorHealth(status="unhealthy", code="reauthentication_required", reason="Notion authentication must be renewed")
        if status_code == 403:
            return ConnectorHealth(status="unhealthy", code="permission_denied", reason="Notion permission was denied")
        if status_code == 429:
            return ConnectorHealth(status="unavailable", code="retryable_provider_error", reason="Notion rate limit was reached")
        return ConnectorHealth(status="unavailable", code="provider_unavailable", reason="Notion is temporarily unavailable")
