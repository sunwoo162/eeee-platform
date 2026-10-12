import httpx
import pytest

from app.integrations.notion_client import NotionClient
from app.plugins.notion_connector import NotionConnector


def connector_for(handler):
    transport = httpx.MockTransport(handler)

    def factory(credential):
        return NotionClient(
            credential["token"], parent_page_id=credential["parentPageId"], transport=transport,
        )

    return NotionConnector(client_factory=factory)


def test_notion_connector_health_uses_existing_client_headers_and_read_scope() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "parent", "url": "https://notion.so/parent"})

    connector = connector_for(handler)
    connection = connector.connect(
        "user-a", {"token": "token-secret", "parentPageId": "parent"}, {"pages.read"}
    )

    health = connector.health(connection)

    assert health.status == "healthy"
    assert seen[0].headers["authorization"] == "Bearer token-secret"
    assert seen[0].headers["notion-version"] == "2026-03-11"
    assert "token-secret" not in health.model_dump_json()


def test_notion_connector_rejects_write_without_explicit_write_scope() -> None:
    connector = connector_for(lambda request: httpx.Response(200, json={"id": "parent"}))
    connection = connector.connect(
        "user-a", {"token": "token-secret", "parentPageId": "parent"}, {"pages.read"}
    )

    with pytest.raises(PermissionError, match="pages.write"):
        connector.invoke(connection, "create_project_page", {"profile": {}, "lines": []})


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [(401, "reauthentication_required"), (403, "permission_denied"),
     (429, "retryable_provider_error"), (503, "provider_unavailable")],
)
def test_notion_provider_errors_map_to_safe_connector_health(
    status_code: int, expected_code: str,
) -> None:
    connector = connector_for(lambda request: httpx.Response(status_code, json={"token": "do-not-leak"}))
    connection = connector.connect(
        "user-a", {"token": "token-secret", "parentPageId": "parent"}, {"pages.read"}
    )

    health = connector.health(connection)

    assert health.status in {"unhealthy", "unavailable"}
    assert health.code == expected_code
    assert "token-secret" not in health.model_dump_json()
    assert "do-not-leak" not in health.model_dump_json()
