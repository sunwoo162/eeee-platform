import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import EventEnvelope, ExecutionEnvelope, ExecutionStatus
from app.harness.state import AgentTask
from app.main import create_app
from tests.api._helpers import wait_for_project_job


@pytest.fixture
def client(tmp_path):
    application = create_app(Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces"))
    store = application.state.coordinator.store
    store.create_project("map-project", "Todo", str(tmp_path), revision="r1")
    store.save_harness_task("map-project", AgentTask(
        id="build", role="frontend", state_version=0, workspace=tmp_path,
        owned_paths=["src"], status="running", project_revision="r1", title="Todo UI",
    ))
    return TestClient(application)


def test_map_route_serializes_actual_task_graph_and_unavailable_checks(client):
    response = client.get("/api/projects/map-project/map")
    assert response.status_code == 200
    result = response.json()
    assert result["projectId"] == "map-project" and result["projectRevision"] == "r1"
    assert result["currentNodeIds"] == ["task:build"]
    node = next(node for node in result["nodes"] if node["id"] == "task:build")
    assert node["title"] == "Todo UI"
    assert node["claimLatchStatus"] == "unavailable" and node["qaStatus"] == "unavailable"
    assert {"source": "iseol:map-project", "target": "task:build", "kind": "contains"} in result["edges"]


@pytest.mark.parametrize("suffix", ["map", "map/events"])
def test_project_map_routes_reject_unknown_and_stale_project(client, suffix):
    assert client.get(f"/api/projects/unknown/{suffix}").status_code == 404
    assert client.get(f"/api/projects/map-project/{suffix}?revision=old").status_code == 409


def test_events_route_uses_durable_cursor_and_validates_cursor(client):
    executions = client.app.state.execution_store
    item = ExecutionEnvelope(execution_id="ex", request_id="r", project_id="map-project",
        project_revision="r1", capability_id="project-execution", tool_id="iseol", actor="ISEOL",
        status=ExecutionStatus.RUNNING)
    executions.save(item)
    for kind in ("execution.running", "task.changed"):
        executions.append_event(EventEnvelope(event_type=kind, execution_id="ex", request_id="r",
            project_id="map-project", project_revision="r1"))

    response = client.get("/api/projects/map-project/map/events?cursor=2")
    assert response.status_code == 200
    result = response.json()
    assert result["cursor"] == 3
    assert [event["eventType"] for event in result["events"]] == ["task.changed"]
    assert result["events"][0]["cursor"] == 3
    assert client.get("/api/projects/map-project/map/events?cursor=-1").status_code == 422
    assert client.get("/api/projects/map-project/map/events?cursor=text").status_code == 422


def test_project_creation_without_plugins_has_readable_map(client):
    response = client.post("/api/assistant/route", json={"text": "Todo 앱 만들어줘"})
    project_id = wait_for_project_job(client, response)["project_id"]
    result = client.get(f"/api/projects/{project_id}/map")
    assert result.status_code == 200
    assert result.json()["projectId"] == project_id
    assert result.json()["nodes"][0]["role"] == "coordinator"
    node_ids = {node["id"] for node in result.json()["nodes"]}
    assert any(node_id.startswith("planning:") for node_id in node_ids)
    assert f"qa:{project_id}" in node_ids
    activity = client.get(f"/api/projects/{project_id}/activity")
    assert activity.status_code == 200
    assert activity.json()["events"]
    # Provisioning completion is not project-work completion.
    assert result.json()["currentNodeIds"]
