from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.api._helpers import wait_for_project_job


def test_desktop_state_exposes_redacted_local_health_and_claim_latch(tmp_path):
    client = TestClient(
        create_app(
            Settings(
                data_dir=tmp_path / "data",
                workspace_root=tmp_path / "workspaces",
                claim_latch_mode="required",
            )
        )
    )

    response = client.get("/api/desktop/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["transport"] == "desktop-local"
    assert payload["claimLatch"] == {
        "status": "configured",
        "mode": "required",
        "profileVersion": "claimlatch-v0.2.0",
        "engineVersion": "0.3.86",
    }
    assert payload["mobileBridge"]["transport"] == "desktop-bridge"
    assert "accessToken" not in payload
    assert "pairingCode" not in payload


def test_desktop_state_includes_selected_project_profile_and_state(tmp_path):
    client = TestClient(
        create_app(
            Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
        )
    )

    route = client.post("/api/assistant/route", json={"text": "웹 프로젝트 하나 만들어줘"})
    assert route.status_code == 200
    project_id = wait_for_project_job(client, route)["project_id"]

    response = client.get("/api/desktop/state", params={"projectId": project_id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["projectId"] == project_id
    assert payload["projectProfile"]["projectId"] == project_id
    assert payload["projectState"]["state"] == "researching"


def test_desktop_events_return_durable_cursor_and_redacted_lifecycle_events(tmp_path):
    client = TestClient(
        create_app(
            Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
        )
    )

    route = client.post("/api/assistant/route", json={"text": "웹 프로젝트 하나 만들어줘"})
    wait_for_project_job(client, route)

    response = client.get("/api/desktop/events", params={"cursor": 0})

    assert response.status_code == 200
    payload = response.json()
    assert payload["cursor"] >= 1
    kinds = [event["kind"] for event in payload["events"]]
    assert "assistant.route.started" in kinds
    assert "project.created" in kinds
    for event in payload["events"]:
        assert "accessToken" not in event
        assert "pairingCode" not in event


def test_desktop_can_issue_pairing_code_without_returning_a_mobile_token(tmp_path):
    client = TestClient(
        create_app(
            Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
        )
    )

    response = client.post("/api/desktop/pairing/code")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"].isdigit()
    assert len(payload["code"]) == 6
    assert "accessToken" not in payload


def test_desktop_control_plane_rejects_non_loopback_callers(tmp_path):
    client = TestClient(
        create_app(
            Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
        ),
        client=("192.0.2.10", 5000),
    )

    response = client.get("/api/desktop/state")

    assert response.status_code == 403


def test_desktop_state_exposes_the_eeee_control_center_snapshot(tmp_path):
    application = create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    )
    with TestClient(application) as client:
        application.state.assistant_supervisor.submit(
            "assistant-control-center", lambda: {"ok": True}
        )
        preference = client.post(
            "/api/memory/user-preference",
            json={"key": "language", "value": "한국어"},
        )
        assert preference.status_code == 200
        response = client.get("/api/desktop/state")

    assert response.status_code == 200
    control_center = response.json()["controlCenter"]
    assert control_center["sections"] == [
        "conversation", "activeWork", "projects", "plugins", "memory", "settings"
    ]
    assert any(item["requestId"] == "assistant-control-center" for item in control_center["jobs"])
    assert control_center["memory"]["activeCount"] >= 1
    assert control_center["plugins"] == []
    assert control_center["verification"]["claimLatch"]["profileVersion"] == "claimlatch-v0.2.0"
