import pytest

from app.iseol.extensions import ExtensionRegistry, ExtensionManifest


def _manifest(extension_id: str, *, capabilities: list[str], enabled: bool = True) -> ExtensionManifest:
    return ExtensionManifest(
        id=extension_id,
        version="1.0.0",
        kind="domain",
        capabilities=capabilities,
        required_connectors=[],
        side_effect_level="none",
        enabled=enabled,
    )


def test_extension_registry_reports_missing_without_side_effect() -> None:
    registry = ExtensionRegistry()
    registry.register(_manifest("meal-planner", capabilities=["project.template.meal-planner"]))
    registry.register(_manifest("gmail", capabilities=["connector.gmail.send", "connector.gmail.read"]))

    selected = registry.select(["project.template.meal-planner"])
    missing = registry.missing(["project.template.meal-planner", "connector.notion.write"])

    assert [item.id for item in selected] == ["meal-planner"]
    assert missing == ["connector.notion.write"]


def test_extension_selection_is_capability_scoped() -> None:
    registry = ExtensionRegistry()
    registry.register(_manifest("meal-planner", capabilities=["project.template.meal-planner"]))
    registry.register(_manifest("notion", capabilities=["connector.notion.write"]))

    assert [item.id for item in registry.select(["project.template.meal-planner"])] == ["meal-planner"]


def test_disabled_extension_is_not_selected() -> None:
    registry = ExtensionRegistry()
    registry.register(_manifest("github", capabilities=["connector.github.write"], enabled=False))

    assert registry.select(["connector.github.write"]) == []
    assert registry.missing(["connector.github.write"]) == ["connector.github.write"]


def test_duplicate_registration_is_idempotent_but_conflicts_are_rejected() -> None:
    registry = ExtensionRegistry()
    manifest = _manifest("meal-planner", capabilities=["project.template.meal-planner"])
    registry.register(manifest)
    registry.register(manifest)

    with pytest.raises(ValueError, match="conflicting"):
        registry.register(manifest.model_copy(update={"capabilities": ["project.template.other"]}))
