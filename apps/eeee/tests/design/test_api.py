from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_design_reference_api_persists_pack_and_tokens(tmp_path):
    client = TestClient(
        create_app(
            Settings(
                data_dir=tmp_path / "data",
                workspace_root=tmp_path / "workspaces",
            )
        )
    )

    created = client.post(
        "/api/design/references",
        json={
            "urls": ["https://example.test/design"],
            "keywords": ["sidebar", "card"],
            "target_type": "web_app",
        },
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["pack"]["references"][0]["allowed_uses"] == ["reference_only"]
    assert payload["tokens"]["sources"] == ["https://example.test/design"]
    assert "direct_asset_copying" not in payload["pack"]["references"][0]["allowed_uses"]

    fetched = client.get(f"/api/design/references/{payload['id']}")

    assert fetched.status_code == 200
    assert fetched.json() == payload
    assert "Collect reference pack" in client.get("/").text


def test_home_surface_is_an_eeee_control_center_not_a_development_only_prompt(tmp_path):
    client = TestClient(
        create_app(
            Settings(
                data_dir=tmp_path / "data",
                workspace_root=tmp_path / "workspaces",
            )
        )
    )

    page = client.get("/").text

    assert 'id="eeee-control-center"' in page
    assert 'id="eeee-active-work"' in page
    assert 'id="eeee-memory-summary"' in page
    assert "Ready for a development request" not in page


def test_design_reference_pack_survives_application_restart(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
    )
    first_client = TestClient(create_app(settings))
    created = first_client.post(
        "/api/design/references",
        json={"urls": ["https://example.test/persisted"], "target_type": "web_app"},
    ).json()

    restarted_client = TestClient(create_app(settings))
    fetched = restarted_client.get(f"/api/design/references/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json() == created


def test_visual_verification_history_survives_application_restart(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "workspaces",
    )
    baseline = tmp_path / "baseline.png"
    baseline.write_bytes(b"baseline")
    first_client = TestClient(create_app(settings))
    created = first_client.post(
        "/api/design/verify",
        json={"url": "http://127.0.0.1:65500", "baseline": str(baseline)},
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["id"]
    assert payload["report"]["status"] == "BLOCKED"

    restarted_client = TestClient(create_app(settings))
    fetched = restarted_client.get(f"/api/design/verify/{payload['id']}")

    assert fetched.status_code == 200
    assert fetched.json() == payload
