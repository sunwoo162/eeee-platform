"""Generic connector adapters for provider APIs and MCP clients."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Literal, Protocol
from urllib.parse import quote
import re

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.plugins.connectors import ConnectorConnection, ConnectorHealth, PluginConnector


class HttpTransport(Protocol):
    def request(self, method: str, url: str, *, headers: Mapping[str, str], json=None): ...


class HttpxTransport:
    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, url: str, *, headers: Mapping[str, str], json=None):
        return httpx.request(
            method, url, headers=dict(headers), json=json, timeout=self.timeout_seconds
        )


class HttpOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(min_length=1)
    permission: str = Field(min_length=1)


class _HttpClientState:
    def __init__(self, token: str) -> None:
        self.token = token


class HttpOpenApiConnector:
    def __init__(
        self,
        plugin_id: str,
        *,
        base_url: str,
        transport: HttpTransport,
        operations: Mapping[str, HttpOperation],
        health_path: str = "/health",
    ) -> None:
        self.plugin_id = plugin_id
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.operations = dict(operations)
        self.health_path = health_path

    def connect(
        self, user_id: str, credential: Mapping[str, str], approved_permissions: set[str]
    ) -> ConnectorConnection:
        token = credential.get("access_token") or credential.get("token")
        if not token:
            raise ValueError("provider access token is required")
        return ConnectorConnection(
            user_id=user_id,
            plugin_id=self.plugin_id,
            approved_permissions=frozenset(approved_permissions),
            client=_HttpClientState(token),
        )

    def disconnect(self, connection: ConnectorConnection) -> None:
        return None

    def health(self, connection: ConnectorConnection) -> ConnectorHealth:
        try:
            response = self.transport.request(
                "GET", f"{self.base_url}{self.health_path}",
                headers=self._headers(connection),
            )
            return _health_from_status(self.plugin_id, response.status_code)
        except Exception:
            return ConnectorHealth(
                status="unavailable",
                code="provider_unavailable",
                reason="Plugin provider health check failed",
            )

    def invoke(
        self, connection: ConnectorConnection, action: str, value: dict[str, object]
    ) -> dict[str, object]:
        operation = self.operations.get(action)
        if operation is None:
            raise KeyError(f"unknown connector action: {action}")
        if operation.permission not in connection.approved_permissions:
            raise PermissionError(f"permission is required: {operation.permission}")
        path, body = _render_operation_path(operation.path, value)
        response = self.transport.request(
            operation.method,
            f"{self.base_url}{path}",
            headers=self._headers(connection),
            json=body,
        )
        health = _health_from_status(self.plugin_id, response.status_code)
        if health.status != "healthy":
            raise RuntimeError(health.reason)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("provider response must be an object")
        return payload

    @staticmethod
    def _headers(connection: ConnectorConnection) -> dict[str, str]:
        client = connection.client
        return {"Authorization": f"Bearer {client.token}"}


class MCPClient(Protocol):
    def health(self) -> Mapping[str, str]: ...

    def invoke(self, action: str, value: dict[str, object]) -> dict[str, object]: ...

    def close(self) -> None: ...


class MCPConnector:
    def __init__(self, plugin_id: str, *, client_factory: Callable[[Mapping[str, str]], MCPClient]) -> None:
        self.plugin_id = plugin_id
        self.client_factory = client_factory

    def connect(
        self, user_id: str, credential: Mapping[str, str], approved_permissions: set[str]
    ) -> ConnectorConnection:
        return ConnectorConnection(
            user_id=user_id,
            plugin_id=self.plugin_id,
            approved_permissions=frozenset(approved_permissions),
            client=self.client_factory(credential),
        )

    def disconnect(self, connection: ConnectorConnection) -> None:
        connection.client.close()

    def health(self, connection: ConnectorConnection) -> ConnectorHealth:
        try:
            return ConnectorHealth.model_validate(connection.client.health())
        except Exception:
            return ConnectorHealth(
                status="unavailable",
                code="provider_unavailable",
                reason="Plugin provider health check failed",
            )

    def invoke(
        self, connection: ConnectorConnection, action: str, value: dict[str, object]
    ) -> dict[str, object]:
        return connection.client.invoke(action, value)


class ConnectorRegistry:
    def __init__(self, connectors: Iterable[PluginConnector]) -> None:
        values = list(connectors)
        ids = [connector.plugin_id for connector in values]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate connector")
        self._connectors = {connector.plugin_id: connector for connector in values}

    def get(self, connector_id: str) -> PluginConnector:
        try:
            return self._connectors[connector_id]
        except KeyError as exc:
            raise KeyError(f"connector is not registered: {connector_id}") from exc

    def as_mapping(self) -> dict[str, PluginConnector]:
        return dict(self._connectors)


def _health_from_status(plugin_id: str, status_code: int) -> ConnectorHealth:
    if 200 <= status_code < 300:
        return ConnectorHealth(status="healthy", code="healthy", reason="provider is healthy")
    if status_code == 401:
        return ConnectorHealth(status="unhealthy", code="reauthentication_required", reason="provider authentication must be renewed")
    if status_code == 403:
        return ConnectorHealth(status="unhealthy", code="permission_denied", reason="provider permission was denied")
    if status_code == 429:
        return ConnectorHealth(status="unavailable", code="retryable_provider_error", reason="provider rate limit was reached")
    if status_code >= 500:
        return ConnectorHealth(status="unavailable", code="provider_unavailable", reason="provider is temporarily unavailable")
    return ConnectorHealth(status="unhealthy", code="provider_error", reason=f"{plugin_id} provider returned HTTP {status_code}")


_PATH_PARAMETER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _render_operation_path(path: str, value: Mapping[str, object]) -> tuple[str, dict[str, object]]:
    """Substitute declared path parameters and keep the request body clean."""

    parameters = set(_PATH_PARAMETER.findall(path))
    body = dict(value)
    for parameter in parameters:
        if parameter not in value:
            raise ValueError(f"path parameter is required: {parameter}")
        raw = value[parameter]
        if not isinstance(raw, (str, int, float, bool)):
            raise ValueError(f"path parameter must be scalar: {parameter}")
        path = path.replace("{" + parameter + "}", quote(str(raw), safe=""))
        body.pop(parameter, None)
    return path, body
