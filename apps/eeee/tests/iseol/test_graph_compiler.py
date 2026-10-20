import pytest

from app.iseol.agents import AgentNode
from app.iseol.contracts import ProjectIntent
from app.iseol.extensions import ExtensionManifest, ExtensionRegistry
from app.iseol.graph import AgentGraphCompiler, _core_catalog


def meal_intent() -> ProjectIntent:
    return ProjectIntent(
        rawText="오늘 식단 정리해주는 웹 만들어줘",
        goal="오늘 식단 정리해주는 웹",
        projectType="web_app",
        templateId="meal_planner",
        constraints=["local-first"],
        assumptions=["local-first", "mobile-first"],
        acceptanceCriteria=["식단을 확인할 수 있음"],
    )


def test_compiler_builds_native_pipeline_without_unrelated_connectors() -> None:
    registry = ExtensionRegistry()
    registry.register(ExtensionManifest(
        id="meal-planner",
        version="1.0.0",
        kind="domain",
        capabilities=["project.template.meal-planner"],
    ))
    registry.register(ExtensionManifest(
        id="gmail",
        version="1.0.0",
        kind="connector",
        capabilities=["connector.gmail.read"],
    ))

    graph = AgentGraphCompiler.compile(meal_intent(), registry)

    assert {node.phase for node in graph.agents} >= {
        "intake", "definition", "requirements", "content", "information_architecture",
        "ux", "ui", "technical_design", "environment", "implementation", "testing",
        "release", "operations", "improvement",
    }
    assert "gmail" not in graph.context["selectedExtensions"]
    assert graph.context["selectedExtensions"] == ["meal-planner"]
    assert graph.by_id("frontend").dependencies
    assert "requirements" in graph.by_id("frontend").dependencies
    assert graph.by_id("frontend").validators
    assert "backend" not in {node.id for node in graph.agents}
    assert graph.by_id("integration").role == "integration"
    assert graph.by_id("release").dependencies == ["integration"]
    assert graph.by_id("operations").dependencies == ["release"]
    assert graph.by_id("improvement").dependencies == ["operations"]


def test_compiler_rejects_duplicate_or_cyclic_catalog() -> None:
    catalog = [
        AgentNode(
            id="a", taskId="a", role="a", title="A", goal="A", phase="implementation",
            validators=["b"], dependencies=["b"],
        ),
        AgentNode(
            id="b", taskId="b", role="b", title="B", goal="B", phase="testing",
            dependencies=["a"],
        ),
    ]

    with pytest.raises(ValueError, match="cycle"):
        AgentGraphCompiler.compile(meal_intent(), ExtensionRegistry(), catalog=catalog)


def test_compiled_graph_has_unique_ids_and_explicit_validator_references() -> None:
    graph = AgentGraphCompiler.compile(meal_intent(), ExtensionRegistry())
    ids = {node.id for node in graph.agents}

    assert len(ids) == len(graph.agents)
    for node in graph.agents:
        assert set(node.dependencies) <= ids
        assert set(node.validators) <= ids
        if node.phase == "implementation":
            assert node.validators


def test_static_intent_skips_backend_and_data_but_keeps_quality_gates() -> None:
    intent = ProjectIntent(
        rawText="포트폴리오 랜딩 페이지 만들어줘",
        goal="포트폴리오 랜딩 페이지",
        projectType="static_app",
        templateId="generic_web",
        acceptanceCriteria=["반응형 랜딩 페이지가 실행됨"],
    )

    graph = AgentGraphCompiler.compile(intent, ExtensionRegistry())
    ids = {node.id for node in graph.agents}

    assert "backend" not in ids
    assert "data" not in ids
    assert {"test", "security", "review", "documentation", "integration"} <= ids
    assert all(set(node.dependencies) <= ids for node in graph.agents)


def test_compiler_preserves_custom_catalog_agents() -> None:
    custom = AgentNode(
        id="brand", taskId="brand", role="brand", title="Brand Agent", goal="브랜드 검토",
        phase="design", dependencies=["ui"],
    )

    graph = AgentGraphCompiler.compile(meal_intent(), ExtensionRegistry(), catalog=[*_core_catalog(), custom])

    assert graph.by_id("brand").id == "brand"
