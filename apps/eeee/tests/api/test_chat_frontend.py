"""Built chat UI is mounted by the same EEEE API process."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_built_chat_ui_served_without_breaking_legacy_root(tmp_path):
    repo_root = Path(__file__).resolve().parents[4]
    if not (repo_root / "apps/desktop/chat-ui/dist/index.html").is_file():
        pytest.skip("chat UI is an optional build artifact")
    app = create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspace")
    )
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        response = client.get("/chat/")
        assert response.status_code == 200
        assert "Gleave" in response.text
        assert "/chat/assets/" in response.text
        assert client.get("/chat").status_code == 200
        assert client.get("/v1/workspaces").status_code == 200
