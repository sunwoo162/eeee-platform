from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plugins.connections import PluginConnection
from app.plugins.credentials import MemoryCredentialStore


def test_catalog_refresh_exposes_approved_permissions_after_oauth_connection(tmp_path) -> None:
    application = create_app(
        Settings(
            data_dir=tmp_path / "data",
            workspace_root=tmp_path / "workspaces",
            claim_latch_auto_start=False,
        )
    )
    application.state.plugin_platform.credentials = MemoryCredentialStore()
    application.state.plugin_platform.connectors["notion"] = object()
    application.state.plugin_platform.install("notion")
    client = TestClient(application)

    # A completed connection writes approved permissions to the platform store.
    application.state.plugin_platform.connections.save(
        PluginConnection(
            userId="local-user",
            pluginId="notion",
            status="connected",
            approvedPermissions=["pages.read"],
            credentialRef="credential-ref",
            accountLabel="Work",
            updatedAt="2026-10-21T00:00:00+09:00",
        )
    )

    catalog = client.get("/api/plugins/catalog").json()
    notion = next(item for item in catalog if item["id"] == "notion")
    assert notion["approvedPermissions"] == ["pages.read"]
    write_detail = next(item for item in notion["permissionDetails"] if item["id"] == "pages.write")
    assert write_detail["requires"] == ["pages.read"]
