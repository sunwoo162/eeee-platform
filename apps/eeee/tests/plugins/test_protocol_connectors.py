import pytest

from app.plugins.connectors import ConnectorConnection
from app.plugins.protocol_connectors import (
    ConnectorRegistry,
    HttpOperation,
    HttpOpenApiConnector,
    MCPConnector,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class FakeHttpTransport:
    def __init__(self, response=None):
        self.response = response or FakeResponse(200, {"ok": True})
        self.calls = []

    def request(self, method, url, *, headers, json=None):
        self.calls.append((method, url, headers, json))
        return self.response


def test_openapi_connector_health_and_invoke_use_declared_operations() -> None:
    transport = FakeHttpTransport(FakeResponse(200, {"items": [1]}))
    connector = HttpOpenApiConnector(
        "github",
        base_url="https://api.example",
        transport=transport,
        health_path="/user",
        operations={
            "repos.list": HttpOperation(
                method="GET", path="/user/repos", permission="repos.read"
            )
        },
    )

    connection = connector.connect("user-a", {"access_token": "secret"}, {"repos.read"})
    assert connector.health(connection).status == "healthy"
    assert connector.invoke(connection, "repos.list", {"visibility": "all"}) == {"items": [1]}
    assert transport.calls[-1][2]["Authorization"] == "Bearer secret"
    assert transport.calls[-1][0] == "GET"


def test_openapi_connector_health_fails_closed_when_transport_raises() -> None:
    class BrokenTransport:
        def request(self, *args, **kwargs):
            raise OSError("network down")

    connector = HttpOpenApiConnector(
        "github", base_url="https://api.example", transport=BrokenTransport(), operations={}
    )
    connection = connector.connect("user-a", {"access_token": "secret"}, set())

    health = connector.health(connection)

    assert health.status == "unavailable"
    assert health.code == "provider_unavailable"


def test_openapi_connector_interpolates_path_parameters_from_value() -> None:
    transport = FakeHttpTransport(FakeResponse(200, {"ok": True}))
    connector = HttpOpenApiConnector(
        "github",
        base_url="https://api.example",
        transport=transport,
        operations={
            "pull_requests.write": HttpOperation(
                method="POST", path="/repos/{owner}/{repo}/pulls", permission="pull_requests.write"
            )
        },
    )
    connection = connector.connect("user-a", {"access_token": "secret"}, {"pull_requests.write"})

    connector.invoke(
        connection,
        "pull_requests.write",
        {"owner": "octo", "repo": "hello-world", "title": "fix"},
    )

    assert transport.calls[-1][1] == "https://api.example/repos/octo/hello-world/pulls"
    assert transport.calls[-1][3] == {"title": "fix"}


def test_openapi_connector_rejects_missing_or_non_scalar_path_parameters() -> None:
    transport = FakeHttpTransport(FakeResponse(200, {"ok": True}))
    connector = HttpOpenApiConnector(
        "figma",
        base_url="https://api.example",
        transport=transport,
        operations={
            "files.get": HttpOperation(method="GET", path="/files/{file_key}", permission="files.read")
        },
    )
    connection = connector.connect("user-a", {"access_token": "secret"}, {"files.read"})

    with pytest.raises(ValueError, match="file_key"):
        connector.invoke(connection, "files.get", {})
    with pytest.raises(ValueError, match="file_key"):
        connector.invoke(connection, "files.get", {"file_key": {"nested": True}})


def test_openapi_connector_blocks_missing_permission_and_maps_provider_errors() -> None:
    transport = FakeHttpTransport(FakeResponse(403, {"error": "forbidden"}))
    connector = HttpOpenApiConnector(
        "github", base_url="https://api.example", transport=transport,
        operations={"repos.write": HttpOperation(method="POST", path="/repos", permission="repos.write")},
    )
    connection = connector.connect("user-a", {"access_token": "secret"}, set())

    with pytest.raises(PermissionError, match="repos.write"):
        connector.invoke(connection, "repos.write", {})
    assert connector.health(connection).code == "permission_denied"


def test_mcp_connector_delegates_to_registered_client_and_closes_it() -> None:
    class Client:
        def __init__(self):
            self.closed = False

        def health(self):
            return {"status": "healthy", "code": "healthy", "reason": "ok"}

        def invoke(self, action, value):
            return {"action": action, "value": value}

        def close(self):
            self.closed = True

    client = Client()
    connector = MCPConnector("linear", client_factory=lambda credential: client)
    connection = connector.connect("user-a", {"access_token": "secret"}, set())

    assert connector.health(connection).status == "healthy"
    assert connector.invoke(connection, "issues.search", {"query": "bug"})["action"] == "issues.search"
    connector.disconnect(connection)
    assert client.closed is True


def test_mcp_connector_health_fails_closed_when_client_raises() -> None:
    class BrokenClient:
        def health(self):
            raise RuntimeError("client down")

    connector = MCPConnector("linear", client_factory=lambda credential: BrokenClient())
    connection = connector.connect("user-a", {"access_token": "secret"}, set())

    health = connector.health(connection)

    assert health.status == "unavailable"
    assert health.code == "provider_unavailable"


def test_connector_registry_rejects_unknown_or_duplicate_ids() -> None:
    connector = MCPConnector("linear", client_factory=lambda credential: object())
    registry = ConnectorRegistry([connector])
    assert registry.get("linear") is connector
    with pytest.raises(KeyError):
        registry.get("missing")
    with pytest.raises(ValueError, match="duplicate connector"):
        ConnectorRegistry([connector, connector])
