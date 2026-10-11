from pathlib import Path

from app.agent.protocol import AgentResult
from app.contracts import ExecutionEnvelope, ExecutionStatus
from app.iseol.agents import AgentTeamFactory
from app.iseol.executor import AgentGraphExecutor, ReflectionDecision
from app.trust.pipeline import TrustPipelineDecision


class RecordingRuntime:
    def __init__(self, *, fail_agent: str | None = None):
        self.calls: list[str] = []
        self.prompts: list[str] = []
        self.fail_agent = fail_agent

    def run(self, request):
        agent_id = request.prompt.split("agentId=")[1].split()[0]
        self.calls.append(agent_id)
        self.prompts.append(request.prompt)
        if agent_id == self.fail_agent and self.calls.count(agent_id) == 1:
            return AgentResult("failed", f"{agent_id} failed", [], [], [], "failed")
        return AgentResult(
            "completed", f"{agent_id} completed", [{"evidenceId": f"evidence-{agent_id}"}],
            [f"src/{agent_id}.py"], [f"pytest tests/{agent_id}"], None,
        )


class PassingTrust:
    def __init__(self, blocked_agent: str | None = None):
        self.blocked_agent = blocked_agent
        self.calls: list[str] = []

    def verify_agent_result(self, envelope, *, agent_id, role, summary, evidence_ids, changed_files):
        self.calls.append(agent_id)
        decision = "BLOCKED" if agent_id == self.blocked_agent else "PASS"
        return TrustPipelineDecision(
            decision=decision,
            reason="blocked for test" if decision == "BLOCKED" else "verified",
            project_id=envelope.project_id,
            project_revision=envelope.project_revision,
            subject_id=envelope.execution_id,
            evidence_ids=list(evidence_ids),
        )


def _envelope() -> ExecutionEnvelope:
    return ExecutionEnvelope(
        execution_id="run-1", request_id="request-1", project_id="project-1",
        project_revision="rev-1", capability_id="project-execution", tool_id="iseol",
        actor="ISEOL", status=ExecutionStatus.RUNNING,
    )


def test_executor_runs_only_ready_nodes_and_verifies_every_handoff(tmp_path):
    runtime = RecordingRuntime()
    trust = PassingTrust()
    executor = AgentGraphExecutor(runtime=runtime, trust_pipeline=trust, workspace=Path(tmp_path))

    report = executor.execute(AgentTeamFactory.default_graph("Todo 앱"), _envelope())

    assert report.status == "completed"
    assert set(runtime.calls) == {
        "requirements", "research", "design", "architecture", "frontend", "backend", "data",
        "accessibility", "security", "test", "review", "documentation", "integration",
    }
    assert set(trust.calls) == set(runtime.calls)
    assert all(item.status == "passed" for item in report.agents)


def test_requirements_and_research_agents_can_leave_evidence_documents():
    graph = AgentTeamFactory.default_graph("Todo 앱")

    assert "workspace.write" in graph.by_id("requirements").allowed_tools
    assert "workspace.write" in graph.by_id("research").allowed_tools


def test_executor_includes_verified_memory_context_in_agent_prompt(tmp_path):
    runtime = RecordingRuntime()
    trust = PassingTrust()
    graph = AgentTeamFactory.default_graph("Todo 앱").model_copy(update={
        "context": {"verifiedMemories": [{"id": "memory-1", "content": "Use FSD boundaries."}]}
    })
    executor = AgentGraphExecutor(runtime=runtime, trust_pipeline=trust, workspace=Path(tmp_path))

    executor.execute(graph, _envelope())

    assert any("Use FSD boundaries." in prompt for prompt in runtime.prompts)


def test_executor_blocks_dependents_after_failed_or_untrusted_handoff(tmp_path):
    runtime = RecordingRuntime()
    trust = PassingTrust(blocked_agent="frontend")
    executor = AgentGraphExecutor(runtime=runtime, trust_pipeline=trust, workspace=Path(tmp_path))

    report = executor.execute(AgentTeamFactory.default_graph("Todo 앱"), _envelope())

    assert report.status == "blocked"
    assert "frontend" in runtime.calls
    assert "test" not in runtime.calls
    assert "integration" not in runtime.calls
    assert report.by_id("frontend").status == "blocked"
    assert report.by_id("test").status == "blocked"


def test_reflector_retries_only_the_failed_agent(tmp_path):
    runtime = RecordingRuntime(fail_agent="frontend")
    trust = PassingTrust()
    executor = AgentGraphExecutor(
        runtime=runtime,
        trust_pipeline=trust,
        workspace=Path(tmp_path),
        reflector=lambda node, record: ReflectionDecision(
            agent_id=node.id, retry=True, diagnosis=record.reason,
            instruction="재시도 전에 누락된 증거를 보강하라",
        ),
    )

    report = executor.execute(AgentTeamFactory.default_graph("Todo 앱"), _envelope())

    assert report.status == "completed"
    assert runtime.calls.count("frontend") == 2
    assert runtime.calls.count("backend") == 1
    assert report.by_id("frontend").attempt == 2
    assert report.by_id("frontend").reflection == "재시도 전에 누락된 증거를 보강하라"


def test_executor_blocks_before_claimlatch_when_quality_gate_finds_secret(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "frontend.py").write_text(
        'API_KEY = "not-a-real-but-secret-looking-value"\n', encoding="utf-8"
    )
    runtime = RecordingRuntime()
    trust = PassingTrust()
    executor = AgentGraphExecutor(runtime=runtime, trust_pipeline=trust, workspace=Path(tmp_path))

    report = executor.execute(AgentTeamFactory.default_graph("Todo 앱"), _envelope())

    frontend = report.by_id("frontend")
    assert frontend.status == "blocked"
    assert frontend.quality_decision == "BLOCK"
    assert frontend.claim_latch_decision == "NOT_RUN"
    assert "secret" in frontend.reason.lower()
    assert "frontend" not in trust.calls
    assert report.by_id("test").status == "blocked"


def test_executor_resumes_from_checkpoint_without_rerunning_verified_agents(tmp_path):
    runtime = RecordingRuntime()
    trust = PassingTrust()
    checkpoint = Path(tmp_path) / "iseol-checkpoint.json"
    graph = AgentTeamFactory.default_graph("Todo 앱").model_copy(update={
        "agents": AgentTeamFactory.default_graph("Todo 앱").agents[:2],
    })

    first = AgentGraphExecutor(
        runtime=runtime, trust_pipeline=trust, workspace=Path(tmp_path),
        checkpoint_path=checkpoint,
    ).execute(graph, _envelope())
    assert first.status == "completed"
    first_calls = list(runtime.calls)

    second = AgentGraphExecutor(
        runtime=runtime, trust_pipeline=trust, workspace=Path(tmp_path),
        checkpoint_path=checkpoint,
    ).execute(graph, _envelope())

    assert second.status == "completed"
    assert runtime.calls == first_calls
