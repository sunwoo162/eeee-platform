import pytest

from app.project_runtime.models import ConnectorBinding, ProjectProfile


def test_project_profile_binds_every_project_surface_under_one_identity() -> None:
    profile = ProjectProfile(
        project_id="project-1",
        project_revision="rev-1",
        goal="Build a personal assistant",
        scope=["web_app"],
        constraints=["local-first"],
        acceptance_criteria=["works offline"],
        workspace="C:/workspaces/project-1",
        capabilities=["project-execution"],
        schedule={"timezone": "Asia/Seoul"},
        preferences={"language": "ko"},
        memory_ids=["memory-1"],
        qa_baseline_ids=["qa-1"],
        connectors=[
            ConnectorBinding(
                connector_id="notion",
                state="awaiting_configuration",
                intent="store project documentation",
                idempotency_key="project-1:rev-1:notion",
                reason="Notion token is not configured",
            )
        ],
        provenance={"goal": "user", "schedule": "inferred"},
    )

    assert profile.project_id == "project-1"
    assert profile.connectors[0].state == "awaiting_configuration"
    assert profile.provisioning_status == "awaiting_configuration"


def test_project_profile_rejects_empty_identity() -> None:
    with pytest.raises(ValueError):
        ProjectProfile(
            project_id="",
            project_revision="rev-1",
            goal="Build something",
            scope=[],
            constraints=[],
            acceptance_criteria=[],
            workspace="C:/workspace",
            capabilities=["project-execution"],
        )


def test_project_profile_round_trips_optional_template_and_quality_fields() -> None:
    profile = ProjectProfile(
        project_id="project-1",
        project_revision="rev-1",
        goal="오늘 식단 웹",
        template_id="meal_planner",
        assumptions=["local-first", "mobile-first"],
        quality_report_path="C:/workspaces/project-1/FINAL-QUALITY-REPORT.json",
        scope=["web_app"],
        constraints=[],
        acceptance_criteria=["오늘 식단을 관리할 수 있음"],
        workspace="C:/workspaces/project-1",
        capabilities=["project-execution"],
    )

    restored = ProjectProfile.model_validate(profile.model_dump(by_alias=True))

    assert restored.template_id == "meal_planner"
    assert restored.assumptions == ["local-first", "mobile-first"]
    assert restored.quality_report_path.endswith("FINAL-QUALITY-REPORT.json")


def test_project_profile_loads_without_new_optional_fields() -> None:
    profile = ProjectProfile.model_validate({
        "projectId": "legacy-project",
        "projectRevision": "rev-1",
        "goal": "Legacy project",
        "scope": [],
        "constraints": [],
        "acceptanceCriteria": [],
        "workspace": "C:/workspaces/legacy-project",
        "capabilities": ["project-execution"],
    })

    assert profile.template_id is None
    assert profile.assumptions == []
    assert profile.quality_report_path is None

