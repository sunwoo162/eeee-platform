from app.iseol.intake import NaturalLanguageIntake
from app.project_runtime.templates import WebTemplateCatalog


def test_meal_request_selects_meal_planner_template() -> None:
    intent = NaturalLanguageIntake.parse("오늘 식단 정리해주는 웹 만들어줘").intent

    template = WebTemplateCatalog.resolve(intent)

    assert template.id == "meal_planner"
    assert "breakfast" in template.capabilities
    assert "local_persistence" in template.capabilities


def test_generic_web_request_keeps_generic_template() -> None:
    intent = NaturalLanguageIntake.parse("카페 홈페이지 웹 만들어줘").intent

    assert WebTemplateCatalog.resolve(intent).id == "generic_web"
