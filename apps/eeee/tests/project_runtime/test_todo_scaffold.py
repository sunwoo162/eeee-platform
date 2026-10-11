import json

from app.project_runtime.scaffold import create_todo_scaffold


def test_todo_scaffold_is_runnable_fsd_and_utf8(tmp_path) -> None:
    result = create_todo_scaffold(tmp_path / "todo-project")
    root = tmp_path / "todo-project"

    assert (root / "index.html").is_file()
    assert (root / "src/app/main.js").is_file()
    assert (root / "src/entities/todo/model.js").is_file()
    assert (root / "src/features/todo-create/ui.js").is_file()
    assert (root / "src/features/todo-edit/ui.js").is_file()
    assert (root / "src/features/todo-filter/ui.js").is_file()
    assert (root / "src/widgets/todo-list/ui.js").is_file()
    assert (root / "src/widgets/todo-stats/ui.js").is_file()
    assert (root / "src/shared/lib/storage.js").is_file()
    assert (root / "tests/e2e/todo-flow.md").is_file()
    assert (root / "DESIGN.md").read_text(encoding="utf-8").startswith("# Todo 프로젝트 디자인")
    manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
    assert manifest["type"] == "module"
    assert manifest["scripts"]["start"] == "python -m http.server 4173"
    assert len(result) >= 10


def test_todo_scaffold_has_product_grade_dashboard_contract(tmp_path) -> None:
    root = tmp_path / "todo-project"
    create_todo_scaffold(root)

    page = (root / "src/pages/todo-page/ui.js").read_text(encoding="utf-8")
    model = (root / "src/entities/todo/model.js").read_text(encoding="utf-8")
    styles = (root / "src/shared/ui/styles.css").read_text(encoding="utf-8")
    e2e = (root / "tests/e2e/todo-flow.md").read_text(encoding="utf-8")

    assert "data-filter" in page
    assert "edit-dialog" in page
    assert "priority" in model
    assert "dueDate" in model
    assert "@media" in styles
    assert "반응형" in e2e


def test_todo_scaffold_is_idempotent_and_does_not_overwrite_user_file(tmp_path) -> None:
    root = tmp_path / "todo-project"
    create_todo_scaffold(root)
    custom = root / "README.custom.md"
    custom.write_text("사용자 메모", encoding="utf-8")

    second = create_todo_scaffold(root)

    assert custom.read_text(encoding="utf-8") == "사용자 메모"
    assert second == []
