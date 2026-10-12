from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_web_control_center_has_plugin_status_surface(tmp_path) -> None:
    client = TestClient(create_app(Settings(
        data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces",
        claim_latch_auto_start=False,
    )))
    page = client.get("/").text
    script = client.get("/static/app.js").text
    styles = client.get("/static/styles.css").text

    assert 'id="eeee-plugin-list"' in page
    assert "renderEeeePluginStatus" in script
    assert "awaiting_authentication" in script
    assert ".eeee-plugin-item" in styles
