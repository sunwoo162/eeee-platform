from __future__ import annotations

import json

import httpx

from app.project_runtime.documents import PluginPlatformNotionAdapter, ProjectDocumentService
from app.project_runtime.models import ConnectorBinding, ProjectProfile
from app.storage.sqlite import SQLiteStore
from app.trust.models import TrustCheck
from app.integrations.notion_client import NotionClient


def _profile() -> ProjectProfile:
    return ProjectProfile(
        project_id="project-1",
        project_revision="rev-1",
        goal="Build a trusted local assistant",
        scope=["web-app"],
        constraints=["local-first"],
        acceptance_criteria=["tests pass"],
        workspace="C:/workspaces/project-1",
        capabilities=["project-execution"],
        connectors=[
            ConnectorBinding(
                connectorId="notion",
                state="planned",
                intent="store project documents",
                idempotencyKey="project-1:notion",
            )
        ],
    )


def _passed_gate() -> object:
    class Gate:
        def verify_action(self, **kwargs: object) -> TrustCheck:
            return TrustCheck(
                subject_id=str(kwargs["subject_id"]),
                project_id=str(kwargs["project_id"]),
                project_revision=str(kwargs["project_revision"]),
                action=str(kwargs["action"]),
                decision="PASS",
                reason="verified",
            )

    return Gate()


def test_notion_client_creates_page_with_versioned_headers_and_blocks() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/pages":
            body = json.loads(request.content)
            assert body["parent"] == {"type": "page_id", "page_id": "parent-1"}
            assert body["properties"]["title"]["title"][0]["text"]["content"] == "Gleave · project-1"
            assert body["children"][0]["type"] == "heading_2"
            return httpx.Response(200, json={"id": "page-1", "url": "https://notion.so/page-1"})
        if request.url.path == "/v1/blocks/page-1/children":
            return httpx.Response(200, json={"results": []})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = NotionClient(
        "secret",
        parent_page_id="parent-1",
        base_url="https://notion.test",
        transport=httpx.MockTransport(handler),
    )

    page = client.create_project_page(_profile(), ["Project specification"])
    client.append_revision(page.id, "rev-1", ["tests pass"])

    assert page.id == "page-1"
    assert len(requests) == 2
    for request in requests:
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.headers["Notion-Version"] == "2026-03-11"


def test_project_document_sync_is_trust_gated_and_idempotent(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    store.create_project("project-1", "Gleave project", str(tmp_path / "workspace"), "rev-1")
    profile = _profile()
    store.save_project_profile(profile)

    class FakeNotion:
        def __init__(self) -> None:
            self.created = 0
            self.appended = 0

        def create_project_page(self, profile: ProjectProfile, lines: list[str]):
            self.created += 1
            return type("Page", (), {"id": "page-1", "url": "https://notion.so/page-1"})()

        def append_revision(self, page_id: str, revision: str, lines: list[str]) -> None:
            self.appended += 1

    notion = FakeNotion()
    service = ProjectDocumentService(store, notion, _passed_gate())

    first = service.sync(profile)
    second = service.sync(profile)

    assert first.status == "synced"
    assert second.status == "unchanged"
    assert notion.created == 1
    assert notion.appended == 0
    assert store.get_project_document("project-1", "notion").external_id == "page-1"
    assert store.get_project_profile("project-1").connector("notion").state == "completed"


def test_project_document_sync_does_not_call_notion_when_claimlatch_blocks(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    store.create_project("project-1", "Gleave project", str(tmp_path / "workspace"), "rev-1")
    profile = _profile()

    class BlockedGate:
        def verify_action(self, **kwargs: object) -> TrustCheck:
            return TrustCheck(
                subject_id="project-document",
                project_id="project-1",
                project_revision="rev-1",
                action="notion.project_document.write",
                decision="BLOCKED",
                reason="stale verification",
            )

    class ShouldNotCall:
        def create_project_page(self, profile: ProjectProfile, lines: list[str]):
            raise AssertionError("Notion must not be called after a blocked trust decision")

    result = ProjectDocumentService(store, ShouldNotCall(), BlockedGate()).sync(profile)

    assert result.status == "blocked"
    assert result.trust.decision == "BLOCKED"


def test_plugin_platform_notion_adapter_uses_connected_connector() -> None:
    class Platform:
        def connected_connector_ids(self, user_id, *, required_permissions):
            assert user_id == "local-user"
            assert required_permissions == {"notion": {"pages.write"}}
            return {"notion"}

        def invoke_connector_action(self, user_id, plugin_id, action, value):
            assert (user_id, plugin_id, action) == ("local-user", "notion", "create_project_page")
            assert value["lines"] == ["Project specification"]
            return {"id": "page-2", "url": "https://notion.so/page-2"}

    adapter = PluginPlatformNotionAdapter(Platform())

    assert adapter.is_available()
    page = adapter.create_project_page(_profile(), ["Project specification"])

    assert page.id == "page-2"
    assert page.url == "https://notion.so/page-2"


def test_project_document_service_routes_plugin_notion_by_user(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    store.init()
    store.create_project("project-1", "Gleave project", str(tmp_path / "workspace"), "rev-1")
    profile = _profile()
    calls: list[tuple[str, str]] = []

    class Platform:
        def connected_connector_ids(self, user_id, *, required_permissions):
            calls.append(("connected", user_id))
            return {"notion"} if user_id == "user-a" else set()

        def invoke_connector_action(self, user_id, plugin_id, action, value):
            calls.append((action, user_id))
            return {"id": "page-user-a", "url": "https://notion.so/page-user-a"}

    service = ProjectDocumentService(
        store, PluginPlatformNotionAdapter(Platform()), _passed_gate()
    )

    result = service.sync(profile, user_id="user-a")

    assert result.status == "synced"
    assert calls == [("connected", "user-a"), ("create_project_page", "user-a")]
