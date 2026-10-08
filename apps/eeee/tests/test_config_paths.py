from pathlib import Path

from app.config import Settings


def test_default_storage_is_user_scoped_not_relative_to_process_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    settings = Settings()

    assert settings.data_dir == tmp_path / "Gleave" / "data"
    assert settings.workspace_root == tmp_path / "Gleave" / "workspaces"
