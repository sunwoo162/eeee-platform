"""Credential-free built-in web template catalog."""

from __future__ import annotations

from dataclasses import dataclass

from app.iseol.contracts import ProjectIntent


@dataclass(frozen=True)
class WebTemplate:
    id: str
    capabilities: tuple[str, ...]
    required_files: tuple[str, ...]
    required_tokens: tuple[str, ...]


class WebTemplateCatalog:
    _templates = {
        "meal_planner": WebTemplate(
            id="meal_planner",
            capabilities=("breakfast", "lunch", "dinner", "local_persistence", "responsive"),
            required_files=(
                "apps/web/index.html",
                "apps/web/src/entities/meal/model.js",
                "apps/web/src/pages/home/ui.js",
                "DESIGN.md",
            ),
            required_tokens=("breakfast", "lunch", "dinner", "localStorage"),
        ),
        "todo_app": WebTemplate(
            id="todo_app",
            capabilities=("crud", "local_persistence", "responsive"),
            required_files=(
                "apps/web/index.html",
                "apps/web/src/entities/todo/model.js",
                "apps/web/src/pages/home/ui.js",
            ),
            required_tokens=("/api/todos", "진행률", "삭제"),
        ),
        "generic_web": WebTemplate(
            id="generic_web",
            capabilities=("responsive", "local_runtime", "agent_implementation_boundary"),
            required_files=("apps/web/index.html", "apps/api/server.py"),
            required_tokens=("viewport", "AUTH_MODE"),
        ),
    }

    @classmethod
    def resolve(cls, intent: ProjectIntent) -> WebTemplate:
        return cls._templates.get(intent.template_id or "generic_web", cls._templates["generic_web"])

    @classmethod
    def by_id(cls, template_id: str) -> WebTemplate:
        return cls._templates.get(template_id, cls._templates["generic_web"])
