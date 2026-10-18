from app.project_runtime.meal_planner_scaffold import MealPlannerTemplate


def test_meal_planner_scaffold_contains_real_vertical_slice_contract(tmp_path) -> None:
    root = tmp_path / "meal-planner"
    created = MealPlannerTemplate.create(root, "오늘 식단")

    assert created
    expected = {
        root / "apps/web/src/entities/meal/model.js",
        root / "apps/web/src/pages/home/ui.js",
        root / "apps/web/index.html",
        root / "DESIGN.md",
    }
    assert expected <= set(created)
    content = "\n".join(path.read_text(encoding="utf-8") for path in expected)
    for token in (
        "오늘", "breakfast", "lunch", "dinner", "추가", "수정", "삭제",
        "empty", "error", "localStorage", "viewport", "반응형",
    ):
        assert token in content
    assert "TODO" not in content
    assert "placeholder" not in content.casefold()
