from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.conversations.models import MessageRole, MessageStatus
from app.integrations.contracts import ProjectOutcomeReportV1
from app.main import create_app


def _outcome() -> ProjectOutcomeReportV1:
    return ProjectOutcomeReportV1.model_validate(
        {
            "schemaVersion": 1,
            "projectId": "project-api-1",
            "requestId": "request-api-1",
            "projectRevision": "rev-1",
            "status": "completed",
            "artifacts": [{"id": "qa-artifact-1"}],
            "agentTeams": [],
            "handoffs": [],
            "deterministicVerification": {"status": "PASS"},
            "qaReport": {
                "status": "PASS",
                "independent": True,
                "evidenceIds": ["qa-evidence-1"],
            },
            "claimLatchReports": [{"id": "claimlatch-1", "decision": "PASS"}],
            "receipts": [],
            "risks": [],
            "memoryCandidates": [
                {
                    "candidateId": "memory-api-1",
                    "kind": "qa_rule",
                    "content": "Run release smoke tests before deployment.",
                    "scope": {"workstream": "release"},
                    "sourceProjectId": "project-api-1",
                    "sourceArtifactIds": ["qa-artifact-1"],
                    "evidenceIds": ["qa-evidence-1"],
                    "verificationIds": ["claimlatch-1"],
                    "confidence": 0.95,
                    "promotionState": "candidate",
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
    )


def test_memory_api_rejects_unverified_outcome_before_memory_promotion(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspace")
    application = create_app(settings)
    client = TestClient(application)

    outcome_response = client.post(
        "/api/projects/project-api-1/outcomes",
        json=_outcome().model_dump(mode="json", by_alias=True),
    )
    assert outcome_response.status_code == 409
    assert "ClaimLatch" in outcome_response.json()["detail"]
    assert client.get("/api/memory", params={"query": "smoke"}).json() == []


def test_memory_api_persists_explicit_user_preference(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspace")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/memory/user-preference",
            json={"key": "language", "value": "한국어", "scope": {"surface": "all"}},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["kind"] == "user_preference"
        assert payload["status"] == "active"
        assert client.get("/api/memory", params={"query": "한국어"}).json()[0]["content"] == "한국어"


def test_memory_api_can_list_lifecycle_records_and_delete_one(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspace")
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/memory/user-preference",
            json={"key": "editor", "value": "vim"},
        ).json()
        listed = client.get("/api/memory", params={"status": "active"})
        assert listed.status_code == 200
        assert any(item["id"] == created["id"] for item in listed.json())

        detail = client.get(f"/api/memory/{created['id']}")
        assert detail.status_code == 200
        deleted = client.post(
            f"/api/memory/{created['id']}/delete",
            json={"actor": "user", "reason": "Forget this preference"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert client.get(f"/api/memory/{created['id']}").status_code == 404


def test_memory_api_keeps_query_and_scope_filters_with_lifecycle_filters(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspace")
    with TestClient(create_app(settings)) as client:
        web = client.post(
            "/api/memory/user-preference",
            json={"key": "web-editor", "value": "vim", "scope": {"technology": "web"}},
        ).json()
        client.post(
            "/api/memory/user-preference",
            json={"key": "mobile-editor", "value": "nano", "scope": {"technology": "mobile"}},
        )

        response = client.get(
            "/api/memory",
            params={"status": "active", "query": "vim", "technology": "web"},
        )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [web["id"]]


def test_memory_feedback_can_be_explicitly_promoted_and_is_idempotent(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspace")
    application = create_app(settings)
    with TestClient(application) as client:
        conversation = client.post("/v1/conversations", json={}).json()
        message = application.state.conversation_store.add_message(
            conversation["id"],
            role=MessageRole.USER,
            content="기억으로 승격할 원문",
            status=MessageStatus.COMPLETED,
            client_message_id="memory-feedback-source",
        )
        payload = {
            "clientFeedbackId": "feedback-api-1",
            "conversationId": conversation["id"],
            "messageId": message.id,
            "rating": "negative",
            "correction": "답변은 항상 결론부터 말해줘.",
            "remember": True,
        }
        first = client.post("/api/memory/feedback", json=payload)
        second = client.post("/api/memory/feedback", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["feedbackId"] == second.json()["feedbackId"]
    assert first.json()["memory"]["status"] == "active"


def test_memory_feedback_rejects_unknown_source_message(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspace")
    application = create_app(settings)
    with TestClient(application) as client:
        conversation = client.post("/v1/conversations", json={}).json()
        response = client.post(
            "/api/memory/feedback",
            json={
                "clientFeedbackId": "feedback-missing-source",
                "conversationId": conversation["id"],
                "messageId": "message-does-not-exist",
                "rating": "negative",
                "correction": "이 기억은 저장되면 안 돼.",
                "remember": True,
            },
        )

    assert response.status_code == 400
    assert "source" in response.json()["detail"]
