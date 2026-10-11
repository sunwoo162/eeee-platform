"""Dependency-aware, parallel execution of the ISEOL specialist graph."""

from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
from typing import Literal
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from app.agent.protocol import AgentRequest, AgentRuntime
from app.contracts import ExecutionEnvelope
from app.iseol.agents import AgentGraph, AgentNode
from app.iseol.evaluator import AcceptanceEvaluator
from app.iseol.quality import QualityGate
from app.trust.pipeline import TrustPipeline


RunStatus = Literal["completed", "blocked", "failed"]
NodeStatus = Literal["passed", "blocked", "failed"]


class AgentExecutionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    agent_id: str = Field(alias="agentId")
    task_id: str = Field(alias="taskId")
    role: str
    status: NodeStatus
    summary: str
    changed_files: list[str] = Field(default_factory=list, alias="changedFiles")
    evidence_ids: list[str] = Field(default_factory=list, alias="evidenceIds")
    claim_latch_decision: str = Field(alias="claimLatchDecision")
    reason: str
    started_at: datetime = Field(alias="startedAt")
    completed_at: datetime = Field(alias="completedAt")
    attempt: int = Field(default=1, ge=1)
    reflection: str | None = None
    acceptance_decision: str = Field(default="NOT_RUN", alias="acceptanceDecision")
    acceptance_gaps: list[str] = Field(default_factory=list, alias="acceptanceGaps")
    quality_decision: str = Field(default="NOT_RUN", alias="qualityDecision")
    quality_checks: list[dict[str, str]] = Field(default_factory=list, alias="qualityChecks")


class ReflectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    agent_id: str = Field(alias="agentId")
    retry: bool
    diagnosis: str = Field(min_length=1)
    instruction: str = Field(min_length=1)


class AgentExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    graph_version: str = Field(alias="graphVersion")
    status: RunStatus
    agents: list[AgentExecutionRecord]

    def by_id(self, agent_id: str) -> AgentExecutionRecord:
        for agent in self.agents:
            if agent.agent_id == agent_id:
                return agent
        raise KeyError(f"Agent execution not found: {agent_id}")


class AgentGraphExecutor:
    """Run specialist nodes and enforce ClaimLatch before every handoff."""

    def __init__(
        self,
        *,
        runtime: AgentRuntime,
        trust_pipeline: TrustPipeline,
        workspace: Path,
        max_parallelism: int = 3,
        reflector: Callable[[AgentNode, AgentExecutionRecord], ReflectionDecision] | None = None,
        max_retries: int = 1,
        acceptance_evaluator: AcceptanceEvaluator | None = None,
        quality_gate: QualityGate | None = None,
        checkpoint_path: Path | None = None,
    ) -> None:
        self.runtime = runtime
        self.trust_pipeline = trust_pipeline
        self.workspace = workspace
        if max_parallelism < 1:
            raise ValueError("max_parallelism must be positive")
        self.max_parallelism = max_parallelism
        self.reflector = reflector
        if max_retries < 0:
            raise ValueError("max_retries must be nonnegative")
        self.max_retries = max_retries
        self.acceptance_evaluator = acceptance_evaluator or AcceptanceEvaluator()
        self.quality_gate = quality_gate or QualityGate(workspace)
        self.checkpoint_path = checkpoint_path

    def execute(self, graph: AgentGraph, envelope: ExecutionEnvelope) -> AgentExecutionReport:
        records: dict[str, AgentExecutionRecord] = {}
        completed_ids: set[str] = set()
        blocked_ids: set[str] = set()
        failed_ids: set[str] = set()
        remaining = {node.id: node for node in graph.agents}
        handoffs: dict[str, AgentExecutionRecord] = {}
        attempts: dict[str, int] = {}

        if self.checkpoint_path is not None:
            restored = self._load_checkpoint(graph)
            for record in restored:
                records[record.agent_id] = record
                if record.status == "passed":
                    completed_ids.add(record.agent_id)
                    handoffs[record.agent_id] = record
                    remaining.pop(record.agent_id, None)

        while remaining:
            to_block = [
                node for node in remaining.values()
                if any(dependency in blocked_ids or dependency in failed_ids for dependency in node.dependencies)
            ]
            for node in to_block:
                records[node.id] = self._blocked(node, datetime.now(timezone.utc), "A dependency did not produce a verified handoff")
                blocked_ids.add(node.id)
                remaining.pop(node.id)
            ready = [
                node for node in remaining.values()
                if all(dependency in completed_ids for dependency in node.dependencies)
            ]
            if not ready:
                for node in remaining.values():
                    records[node.id] = self._blocked(node, datetime.now(timezone.utc), "Agent graph has an unresolved dependency or cycle")
                    blocked_ids.add(node.id)
                break
            batch = ready[: self.max_parallelism]
            with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix="iseol-agent") as pool:
                futures = {
                    node.id: pool.submit(self._run_node, node, envelope, handoffs, graph.context)
                    for node in batch
                }
                for node in batch:
                    record = futures[node.id].result()
                    while (
                        record.status != "passed"
                        and self.reflector is not None
                        and attempts.get(node.id, 0) < self.max_retries
                    ):
                        attempts[node.id] = attempts.get(node.id, 0) + 1
                        reflection = self.reflector(node, record)
                        if reflection.agent_id != node.id or not reflection.retry:
                            break
                        record = self._run_node(
                            node, envelope, handoffs,
                            graph.context,
                            reflection=reflection.instruction,
                            attempt=attempts[node.id] + 1,
                        ).model_copy(update={"reflection": reflection.instruction})
                    records[node.id] = record
                    if record.status == "passed":
                        completed_ids.add(node.id)
                        handoffs[node.id] = record
                    elif record.status == "failed":
                        failed_ids.add(node.id)
                    else:
                        blocked_ids.add(node.id)
                    remaining.pop(node.id)
                    self._write_checkpoint(graph, records)

        status: RunStatus = "failed" if failed_ids else (
            "completed" if len(completed_ids) == len(graph.agents) else "blocked"
        )
        return AgentExecutionReport(
            graphVersion=graph.schema_version, status=status,
            agents=[records[node.id] for node in graph.agents],
        )

    def _load_checkpoint(self, graph: AgentGraph) -> list[AgentExecutionRecord]:
        if self.checkpoint_path is None or not self.checkpoint_path.is_file():
            return []
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            if payload.get("graphVersion") != graph.schema_version:
                return []
            expected = {node.id for node in graph.agents}
            records = [
                AgentExecutionRecord.model_validate(item)
                for item in payload.get("agents", [])
                if isinstance(item, dict) and item.get("agentId") in expected
            ]
            return [record for record in records if record.status == "passed"]
        except (OSError, ValueError, TypeError):
            return []

    def _write_checkpoint(self, graph: AgentGraph, records: dict[str, AgentExecutionRecord]) -> None:
        if self.checkpoint_path is None:
            return
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        status = "completed" if len(records) == len(graph.agents) and all(
            record.status == "passed" for record in records.values()
        ) else "blocked"
        payload = {
            "graphVersion": graph.schema_version,
            "status": status,
            "agents": [
                records[node.id].model_dump(mode="json", by_alias=True)
                for node in graph.agents if node.id in records
            ],
        }
        temporary = self.checkpoint_path.with_suffix(self.checkpoint_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.checkpoint_path)

    def _run_node(self, node: AgentNode, envelope: ExecutionEnvelope,
                  handoffs: dict[str, AgentExecutionRecord], shared_context: dict[str, object], *,
                  reflection: str | None = None, attempt: int = 1) -> AgentExecutionRecord:
        started = datetime.now(timezone.utc)
        dependency_context = "\n".join(
            f"{dependency}: {handoffs[dependency].summary}; evidence={handoffs[dependency].evidence_ids}"
            for dependency in node.dependencies if dependency in handoffs
        ) or "none"
        prompt = (
            f"{node.system_prompt}\n"
            f"You are ISEOL agent role={node.role} agentId={node.id} taskId={node.task_id}.\n"
            f"Goal: {node.goal}\n"
            "The canonical intent is authoritative for equivalent user wording; do not reinterpret it.\n"
            f"Acceptance criteria: {node.acceptance_criteria}\n"
            f"Verified dependency handoffs:\n{dependency_context}\n"
            f"Verified EEEE memory context:\n{json.dumps(shared_context, ensure_ascii=False, sort_keys=True)}\n"
            f"Reflector instruction: {reflection or 'none'}\n"
            "Return only work backed by files, commands, tests, and evidence."
        )
        result = self.runtime.run(AgentRequest(
            prompt=prompt, workspace=self.workspace,
            allowed_actions=list(node.allowed_tools), run_id=f"{envelope.execution_id}:{node.id}",
        ))
        evidence_ids = [
            str(event["evidenceId"])
            for event in result.events
            if isinstance(event, dict) and isinstance(event.get("evidenceId"), str)
        ]
        if result.status != "completed":
            return AgentExecutionRecord(
                agentId=node.id, taskId=node.task_id, role=node.role, status="failed",
                summary=result.summary, changedFiles=list(result.changed_files),
                evidenceIds=evidence_ids, claimLatchDecision="NOT_RUN",
                reason=result.error or "Agent runtime did not complete",
                startedAt=started, completedAt=datetime.now(timezone.utc), attempt=attempt,
            )
        acceptance = self.acceptance_evaluator.evaluate(node, result, evidence_ids=evidence_ids)
        if acceptance.decision != "PASS":
            return AgentExecutionRecord(
                agentId=node.id, taskId=node.task_id, role=node.role, status="blocked",
                summary=result.summary, changedFiles=list(result.changed_files),
                evidenceIds=evidence_ids, claimLatchDecision="NOT_RUN",
                reason=acceptance.reason, acceptanceDecision=acceptance.decision,
                acceptanceGaps=acceptance.gaps,
                startedAt=started, completedAt=datetime.now(timezone.utc), attempt=attempt,
            )
        quality = self.quality_gate.evaluate(node, result)
        quality_checks = [check.model_dump() for check in quality.checks]
        if quality.decision == "BLOCK":
            return AgentExecutionRecord(
                agentId=node.id, taskId=node.task_id, role=node.role, status="blocked",
                summary=result.summary, changedFiles=list(result.changed_files),
                evidenceIds=evidence_ids, claimLatchDecision="NOT_RUN",
                reason="; ".join(check.message for check in quality.checks if check.status == "BLOCK"),
                acceptanceDecision=acceptance.decision, qualityDecision=quality.decision,
                qualityChecks=quality_checks,
                startedAt=started, completedAt=datetime.now(timezone.utc), attempt=attempt,
            )
        child = envelope.model_copy(update={
            "execution_id": f"{envelope.execution_id}:{node.id}",
            "capability_id": f"iseol.agent.{node.id}",
            "evidence_ids": tuple(evidence_ids),
        })
        trust = self.trust_pipeline.verify_agent_result(
            child, agent_id=node.id, role=node.role, summary=result.summary,
            evidence_ids=evidence_ids, changed_files=list(result.changed_files),
        )
        return AgentExecutionRecord(
            agentId=node.id, taskId=node.task_id, role=node.role,
            status="passed" if trust.decision == "PASS" else "blocked",
            summary=result.summary, changedFiles=list(result.changed_files),
            evidenceIds=evidence_ids, claimLatchDecision=trust.decision,
            reason=trust.reason, startedAt=started, completedAt=datetime.now(timezone.utc),
            attempt=attempt,
            acceptanceDecision=acceptance.decision,
            qualityDecision=quality.decision,
            qualityChecks=quality_checks,
        )

    @staticmethod
    def _blocked(node: AgentNode, started: datetime, reason: str) -> AgentExecutionRecord:
        return AgentExecutionRecord(
            agentId=node.id, taskId=node.task_id, role=node.role, status="blocked",
            summary="Agent was not started", claimLatchDecision="NOT_RUN", reason=reason,
            startedAt=started, completedAt=datetime.now(timezone.utc),
        )
