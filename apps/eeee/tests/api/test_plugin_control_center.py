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
    assert 'id="eeee-plugin-search"' in page
    assert "설치된 플러그인" in page
    assert "플러그인 둘러보기" in page
    assert "renderEeeePluginStatus" in script
    assert "eeee-plugin-search" in script
    assert 'nextActionLabels = { install: "설치"' in script
    assert 'open: "열기"' in script
    assert "setupMessage" in script
    assert "/oauth/start" in script
    assert "approvedPermissions" in script
    assert "/launch" in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "plugin-action" in script
    assert "awaiting_authentication" in script
    assert ".eeee-plugin-item" in styles
