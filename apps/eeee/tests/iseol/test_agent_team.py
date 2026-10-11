from app.iseol.agents import AgentTeamFactory


def test_default_team_contains_executable_roles_and_dependencies():
    graph = AgentTeamFactory.default_graph("Todo 앱")

    assert [agent.id for agent in graph.agents] == [
        "requirements", "research", "design", "architecture", "frontend", "backend", "data",
        "accessibility", "security", "test", "review", "documentation", "integration"
    ]
    assert graph.task_ids == [agent.task_id for agent in graph.agents]
    assert graph.by_id("frontend").dependencies == ["requirements", "design", "architecture"]
    assert graph.by_id("review").dependencies == ["frontend", "backend", "data", "security"]
    assert graph.by_id("integration").dependencies == ["test", "review", "accessibility", "security", "documentation"]


def test_agent_team_serializes_to_project_organization_nodes():
    graph = AgentTeamFactory.default_graph("Todo 앱")

    payload = graph.model_dump(mode="json", by_alias=True)

    assert payload["schemaVersion"] == "iseol-agent-graph.v1"
    assert payload["agents"][0]["executionPolicy"] == "claimlatch_before_handoff"
    assert payload["agents"][-1]["role"] == "integration"
