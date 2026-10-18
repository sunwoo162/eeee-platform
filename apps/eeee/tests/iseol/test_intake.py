from app.iseol.contracts import ProjectIntent
from app.iseol.intake import NaturalLanguageIntake


def test_intake_preserves_original_and_extracts_korean_meal_web_request() -> None:
    text = "오늘 식단 정리해주는 웹 만들어줘"

    result = NaturalLanguageIntake.parse(text)

    assert result.intent.raw_text == text
    assert result.intent.project_type == "web_app"
    assert result.intent.template_id == "meal_planner"
    assert "local-first" in result.intent.assumptions
    assert "mobile-first" in result.intent.assumptions
    assert result.intent.acceptance_criteria
    assert result.questions == []
    assert result.ready is True


def test_intake_bundles_only_blocking_questions() -> None:
    vague = NaturalLanguageIntake.parse("이거 해줘")
    concrete = NaturalLanguageIntake.parse("카페 홈페이지 웹 만들어줘")

    assert vague.intent.project_type == "unknown"
    assert vague.ready is False
    assert len(vague.questions) == 1
    assert concrete.intent.project_type == "web_app"
    assert concrete.questions == []
    assert concrete.ready is True


def test_project_intent_projects_into_legacy_request_brief() -> None:
    intent = ProjectIntent(
        raw_text="메모 웹 만들어줘",
        goal="메모 웹",
        project_type="web_app",
        template_id="generic_web",
        constraints=["local-first"],
        assumptions=["local-first"],
        acceptance_criteria=["실행 가능한 결과물"],
        risk_level="low",
    )

    brief = intent.to_request_brief()

    assert brief.raw_text == intent.raw_text
    assert brief.goal == intent.goal
    assert brief.target_type == "web_app"
    assert brief.runtime_profile == "web_app"
    assert brief.canonical_intent == "project.create.web_app"
    assert brief.needs_confirmation is False
