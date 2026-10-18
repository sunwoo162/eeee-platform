import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_core_dependency_list_does_not_require_desktop_or_optional_agent_sdks():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    core_dependencies = pyproject.split("[project.optional-dependencies]", 1)[0]
    assert "PySide6" not in core_dependencies
    assert "playwright" not in core_dependencies.lower()
    assert "openhands" not in core_dependencies.lower()


def test_main_idle_imports_optional_agent_modules_only_inside_factories():
    main = ast.parse((ROOT / "app" / "main.py").read_text(encoding="utf-8"))
    top_level_imports = [
        node for node in main.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    rendered = ast.unparse(ast.Module(body=top_level_imports, type_ignores=[]))

    assert "app.agent.iseol_runtime" not in rendered
    assert "app.agent.openhands_runtime" not in rendered
    assert "app.agent.chatgpt_web_runtime" not in rendered
