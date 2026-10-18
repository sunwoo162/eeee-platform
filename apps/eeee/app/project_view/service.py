"""Project real task leases and durable results, without executing any work."""

from collections.abc import Mapping
from contextlib import closing, contextmanager
import json
from pathlib import Path

from app.contracts import EventEnvelope, ExecutionEnvelope
from app.activity.store import ActivityLedger
from app.harness.state import AgentTask, ProjectState
from app.iseol.review import FinalProjectReport
from app.project_view.models import ProjectMapEdge, ProjectMapEvents, ProjectMapNode, ProjectMapSnapshot
from app.runtime.store import StaleProjectRevision
from app.storage.sqlite import SQLiteStore


_ROLE_ORDER = {
    "coordinator": 0, "planning": 1, "pm": 1, "decomposer": 1,
    "team-factory": 2, "design": 3, "frontend": 4, "backend": 5,
    "data": 6, "docs": 7, "review": 8, "qa": 9, "test": 9,
    "integration": 10, "release": 11,
}
_STATUSES = {
    "pending": "waiting", "queued": "waiting", "waiting": "waiting", "idle": "waiting",
    "awaiting_approval": "blocked", "running": "active", "active": "active",
    "working": "active", "researching": "active", "verifying": "active",
    "handed_off": "completed", "completed": "completed", "blocked": "blocked",
    "failed": "failed", "cancelled": "cancelled",
}


class ProjectViewService:
    def __init__(self, store: SQLiteStore, activity: ActivityLedger | None = None) -> None:
        self.store = store
        self.activity = activity or ActivityLedger(store)

    @contextmanager
    def _read(self, project_id: str, revision: str | None):
        # One SQLite read snapshot covers identity, tasks, receipts and cursor.
        # A concurrent update cannot mix two revisions in one response.
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN")
            project = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if project is None:
                raise KeyError(f"Project not found: {project_id}")
            if revision is not None and revision != project["revision"]:
                raise StaleProjectRevision(f"stale project revision for {project_id}: {revision}")
            yield connection, project

    def get_snapshot(self, project_id: str, revision: str | None = None) -> ProjectMapSnapshot:
        with self._read(project_id, revision) as (connection, project):
            revision = project["revision"]
            state_row = connection.execute("SELECT state_json FROM harness_states WHERE project_id = ?", (project_id,)).fetchone()
            state = ProjectState.model_validate_json(state_row[0]) if state_row else None
            tasks = [AgentTask.model_validate_json(row[0]) for row in connection.execute(
                "SELECT task_json FROM harness_tasks WHERE project_id = ? ORDER BY id", (project_id,),
            )]
            # Keep legacy unversioned leases visible, labelled unknown. Never
            # attach trusted results to them by guessing their revision.
            tasks = [task for task in tasks if (task.project_revision or (state.project_revision if state else None)) in {None, revision}]
            executions = {item.execution_id: item for item in (
                ExecutionEnvelope.model_validate_json(row[0]) for row in connection.execute(
                    "SELECT envelope_json FROM execution_envelopes WHERE project_id = ? AND project_revision = ? "
                    "AND capability_id = 'project-execution' ORDER BY started_at, execution_id", (project_id, revision),
                )
            )}
            report_refs = {}
            task_ids = {task.id for task in tasks}
            for row in connection.execute(
                "SELECT * FROM tasks WHERE project_id = ? AND revision = ? ORDER BY id", (project_id, revision),
            ):
                if row["id"] in task_ids:
                    continue
                candidates = [item for item in executions.values() if item.tool_id == "iseol" and item.request_id == row["request_id"]]
                # The request ID is a durable association, not a time heuristic.
                # Multiple attempts remain separate unless a task names one.
                associated = candidates[0] if len(candidates) == 1 else None
                tasks.append(AgentTask(
                    id=row["id"], role="iseol", state_version=0, workspace=project["workspace"],
                    owned_paths=[], status=row["state"], title=row["message"], project_revision=revision,
                    execution_id=associated.execution_id if associated else None,
                ))
                report_refs[row["id"]] = row["report_id"]
            tasks.sort(key=lambda task: (_ROLE_ORDER.get(task.role.casefold(), 12), task.role.casefold(), task.id))
            root_id = f"iseol:{project_id}"
            root = ProjectMapNode(
                id=root_id, role="coordinator", group="coordinator", title="ISEOL Coordinator",
                status=_status(project["state"]), project_revision=revision, revision_status="current",
                current_commit=state.current_commit if state and state.project_revision == revision else None,
            )
            nodes = [root]
            planning_sessions = [item for item in self.store.list_planning_sessions(project_id, revision)]
            if planning_sessions:
                session = planning_sessions[-1]
                nodes.append(ProjectMapNode(
                    id=f"planning:{session.session_id}", role="planning", group="planning",
                    title="EEEE Planning Room", status=_status(session.status), project_revision=revision,
                    revision_status="current", reason="Convert the user request into an approved execution handoff",
                    selected_because="Every project must be planned before ISEOL execution",
                ))
                nodes.append(ProjectMapNode(
                    id=f"qa:{project_id}", role="qa", group="quality", title="ISEOL QA",
                    status="waiting", project_revision=revision, revision_status="current",
                    reason="Independent verification follows implementation",
                ))
                nodes.append(ProjectMapNode(
                    id=f"claimlatch:{project_id}", role="claimlatch", group="quality", title="ClaimLatch",
                    status="waiting", project_revision=revision, revision_status="current",
                    reason="Verify claims, evidence, hashes, and revision identity",
                ))
                nodes.append(ProjectMapNode(
                    id=f"memory:{project_id}", role="memory", group="memory", title="Memory Promotion Gate",
                    status="waiting", project_revision=revision, revision_status="current",
                    reason="Promote only verified project outcomes and decisions",
                ))
            agent_graph, agent_report = self._agent_graph(executions)
            if agent_graph:
                report_by_id = {
                    item.get("agentId"): item
                    for item in agent_report.get("agents", [])
                    if isinstance(item, Mapping) and isinstance(item.get("agentId"), str)
                }
                for agent in agent_graph.get("agents", []):
                    if not isinstance(agent, Mapping) or not isinstance(agent.get("id"), str):
                        continue
                    agent_id = agent["id"]
                    record = report_by_id.get(agent_id, {})
                    claim = str(record.get("claimLatchDecision", "unavailable"))
                    quality = str(record.get("qualityDecision", "unavailable"))
                    quality_checks = [
                        str(check.get("message"))
                        for check in record.get("qualityChecks", [])
                        if isinstance(check, Mapping) and isinstance(check.get("message"), str)
                    ]
                    nodes.append(ProjectMapNode(
                        id=f"agent:{agent_id}", role=str(agent.get("role", agent_id)), group="implementation",
                        title=str(agent.get("title", agent_id)), status=_agent_status(record.get("status")),
                        progress=100 if record.get("status") == "passed" else None,
                        project_revision=revision, revision_status="current",
                        execution_id=_string(record.get("executionId")),
                        changed_files=_strings(record.get("changedFiles")),
                        claim_latch_status={"BLOCKED": "BLOCK", "PASS": "PASS", "WARN": "WARN"}.get(claim, "unavailable"),
                        qa_status=quality if quality in {"PASS", "WARN", "BLOCK"} else "unavailable",
                        evidence_ids=_strings(record.get("evidenceIds")),
                        reason=_string(record.get("reason")) or str(agent.get("goal", "")),
                        selected_because="Dependencies and handoff gates determine when this specialist may run",
                        trust_blockers=[*_strings(record.get("acceptanceGaps")), *quality_checks],
                        started_at=record.get("startedAt"), completed_at=record.get("completedAt"),
                    ))
            linked = set()
            warnings = []
            for task in tasks:
                # A later shared state is not proof of an old lease's identity.
                task_revision = task.project_revision
                execution = executions.get(task.execution_id) if task_revision == revision else None
                if execution is not None:
                    linked.add(execution.execution_id)
                elif task.execution_id:
                    warnings.append(f"Task {task.id}: execution reference unavailable for current revision")
                output = (execution.output or {}) if execution else {}
                node = ProjectMapNode(
                    id=f"task:{task.id}", role=task.role, group=task.role, title=task.title or task.id,
                    status=_status(task.status), progress=task.progress,
                    project_revision=task_revision, revision_status="current" if task_revision == revision else "unavailable",
                    execution_id=task.execution_id, current_commit=_string(task.handoff.get("commit")) or _string(output.get("commit")),
                    changed_files=_unique([*_strings(task.handoff.get("changed_files")), *_strings(output.get("changedFiles"))]),
                    qa_report_id=report_refs.get(task.id),
                    evidence_ids=_unique([
                        *_strings(task.handoff.get("evidence_paths", task.handoff.get("evidence"))),
                        *(execution.evidence_ids if execution else ()),
                    ]),
                    troubleshooting_ids=task.troubleshooting_ids,
                    started_at=task.started_at or (execution.started_at if execution else None),
                    # A request-associated provisioning envelope is not the
                    # work task's completion clock. Only explicit task links
                    # can supply a fallback terminal timestamp.
                    completed_at=task.completed_at or (
                        execution.completed_at if execution and task.id not in report_refs
                        and task.status in {"handed_off", "completed", "failed", "cancelled"} else None
                    ),
                )
                nodes.append(self._trust(connection, project_id, revision, node, execution, task.id))
            for execution in executions.values():
                if execution.execution_id in linked or execution.tool_id != "iseol":
                    continue
                output = execution.output or {}
                node = ProjectMapNode(
                    id=f"execution:{execution.execution_id}", role="iseol", group="iseol",
                    title="ISEOL Project Execution", status=_status(execution.status.value),
                    project_revision=revision, revision_status="current", execution_id=execution.execution_id,
                    evidence_ids=list(execution.evidence_ids), started_at=execution.started_at,
                    completed_at=execution.completed_at,
                    current_commit=_string(output.get("commit")), changed_files=_strings(output.get("changedFiles")),
                    troubleshooting_ids=_strings(output.get("troubleshootingIds")),
                )
                nodes.append(self._trust(connection, project_id, revision, node, execution))
            activity_cursor = self.activity.list(project_id, revision, validate_revision=False).cursor
            edges = self._edges(root_id, tasks, nodes, warnings)
            edges.extend(self._agent_edges(agent_graph, nodes, root_id, warnings))
            edges = _unique_edges(edges)
            nodes = self._depths(nodes, edges, warnings)
            return ProjectMapSnapshot(
                project_id=project_id, project_revision=revision, title=project["name"],
                nodes=nodes, edges=edges, current_node_ids=[node.id for node in nodes[1:] if node.status == "active"],
                cursor=self._cursor(connection, project_id, revision), warnings=warnings,
                activity_cursor=activity_cursor,
            )

    @staticmethod
    def _agent_graph(executions):
        for execution in reversed(list(executions.values())):
            output = execution.output or {}
            graph = output.get("agentGraph")
            report = output.get("agentExecutionReport")
            if isinstance(graph, Mapping) and isinstance(graph.get("agents"), (list, tuple)):
                return graph, report if isinstance(report, Mapping) else {}
        return {}, {}

    def get_events(self, project_id: str, *, cursor: int = 0, revision: str | None = None) -> ProjectMapEvents:
        if cursor < 0:
            raise ValueError("cursor must be nonnegative")
        with self._read(project_id, revision) as (connection, project):
            revision = project["revision"]
            events = [EventEnvelope.model_validate_json(row[0]) for row in connection.execute(
                "SELECT event_json FROM execution_events WHERE project_id = ? AND project_revision = ? "
                "AND cursor > ? ORDER BY cursor", (project_id, revision, cursor),
            )]
            return ProjectMapEvents(project_id=project_id, project_revision=revision,
                cursor=max(cursor, self._cursor(connection, project_id, revision)), events=events)

    def get_activity(self, project_id: str, *, cursor: int = 0, revision: str | None = None):
        project = self.store.get_project(project_id)
        current = revision or project.revision
        if current != project.revision:
            raise StaleProjectRevision(f"stale project revision for {project_id}: {current}")
        return self.activity.list(project_id, current, cursor)

    def get_quality(self, project_id: str, revision: str | None = None) -> dict[str, object]:
        """Return the durable final report, or an explicit awaiting state."""

        with self._read(project_id, revision) as (_connection, project):
            current_revision = str(project["revision"])
            root = Path(str(project["workspace"])).resolve()
            report_path = root / "FINAL-QUALITY-REPORT.json"
            if not report_path.is_file():
                return {
                    "status": "awaiting",
                    "projectId": project_id,
                    "projectRevision": current_revision,
                    "reason": "최종 품질 리포트가 아직 생성되지 않았어.",
                }
            try:
                report = FinalProjectReport.model_validate_json(report_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                return {
                    "status": "blocked",
                    "projectId": project_id,
                    "projectRevision": current_revision,
                    "reason": f"최종 품질 리포트를 읽지 못했어: {type(exc).__name__}",
                }
            if report.project_id != project_id or report.project_revision != current_revision:
                return {
                    "status": "blocked",
                    "projectId": project_id,
                    "projectRevision": current_revision,
                    "reason": "최종 품질 리포트의 프로젝트 revision이 현재 상태와 달라.",
                }
            return report.model_dump(mode="json", by_alias=True)

    def get_execution_plan(self, project_id: str, revision: str | None = None) -> dict[str, object]:
        """Expose safe plan progress without raw prompts or agent instructions."""

        with self._read(project_id, revision) as (_connection, project):
            current_revision = str(project["revision"])
            path = Path(str(project["workspace"])).resolve() / "execution-plan.json"
            if not path.is_file():
                return {
                    "status": "awaiting",
                    "projectId": project_id,
                    "projectRevision": current_revision,
                    "phases": [],
                    "selectedExtensions": [],
                    "missingExtensions": [],
                    "tasks": [],
                }
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return {
                    "status": "blocked",
                    "projectId": project_id,
                    "projectRevision": current_revision,
                    "reason": "execution-plan.json을 읽지 못했어.",
                }
            if not isinstance(value, Mapping) or value.get("projectId") != project_id or value.get("projectRevision") != current_revision:
                return {
                    "status": "blocked",
                    "projectId": project_id,
                    "projectRevision": current_revision,
                    "reason": "실행 계획의 프로젝트 identity가 현재 상태와 달라.",
                }
            graph = value.get("agentGraph") if isinstance(value.get("agentGraph"), Mapping) else {}
            context = graph.get("context") if isinstance(graph.get("context"), Mapping) else {}
            agents = graph.get("agents") if isinstance(graph.get("agents"), list) else []
            execution = value.get("agentExecutionReport") if isinstance(value.get("agentExecutionReport"), Mapping) else {}
            records = {
                item.get("agentId"): item
                for item in execution.get("agents", [])
                if isinstance(item, Mapping) and isinstance(item.get("agentId"), str)
            }
            tasks = []
            for agent in agents:
                if not isinstance(agent, Mapping) or not isinstance(agent.get("id"), str):
                    continue
                record = records.get(agent["id"], {})
                tasks.append({
                    "id": agent["id"],
                    "taskId": agent.get("taskId", agent["id"]),
                    "title": agent.get("title", agent["id"]),
                    "role": agent.get("role", agent["id"]),
                    "phase": agent.get("phase"),
                    "dependencies": list(agent.get("dependencies", [])) if isinstance(agent.get("dependencies"), list) else [],
                    "status": record.get("status", "planned"),
                })
            phases = context.get("phases") if isinstance(context.get("phases"), list) else [
                task["phase"] for task in tasks if isinstance(task.get("phase"), str)
            ]
            intent = value.get("intent") if isinstance(value.get("intent"), Mapping) else {}
            safe_intent = {
                key: intent[key]
                for key in ("schemaVersion", "goal", "projectType", "templateId", "targetAudience", "acceptanceCriteria", "riskLevel", "requiresExternalApproval")
                if key in intent
            }
            return {
                "status": value.get("status", "planned"),
                "projectId": project_id,
                "projectRevision": current_revision,
                "requestId": value.get("requestId"),
                "nativePlan": value.get("nativePlan", False),
                "intent": safe_intent,
                "phases": list(dict.fromkeys(str(item) for item in phases if isinstance(item, str))),
                "selectedExtensions": [item for item in value.get("selectedExtensions", context.get("selectedExtensions", [])) if isinstance(item, str)],
                "missingExtensions": [item for item in value.get("missingExtensions", context.get("missingExtensions", [])) if isinstance(item, str)],
                "tasks": tasks,
            }

    @staticmethod
    def _cursor(connection, project_id, revision) -> int:
        return connection.execute(
            "SELECT COALESCE(MAX(cursor), 0) FROM execution_events WHERE project_id = ? AND project_revision = ?",
            (project_id, revision),
        ).fetchone()[0]

    @staticmethod
    def _trust(connection, project_id, revision, node, execution, task_id=None):
        if node.revision_status != "current":
            return node
        receipt_id = execution.claim_latch_receipt_id if execution else node.claim_latch_receipt_id
        report_id = node.qa_report_id or (execution.qa_report_id if execution else None)
        subjects = {task_id}
        if execution is not None:
            subjects.add(execution.execution_id)
        values = {"claim_latch_receipt_id": receipt_id, "qa_report_id": report_id}
        audit = connection.execute(
            "SELECT subject_id, decision FROM claimlatch_audits WHERE project_id = ? AND project_revision = ? "
            "AND receipt_id = ? ORDER BY created_at DESC", (project_id, revision, receipt_id),
        ).fetchall()
        matching = [row for row in audit if row["subject_id"] in subjects]
        # Ambiguous receipts cannot silently select a favourable decision.
        if matching and len({row["decision"] for row in matching}) == 1:
            values["claim_latch_status"] = matching[0]["decision"]
        report = connection.execute(
            "SELECT task_id, status, checks_json FROM reports WHERE id = ? AND project_id = ? AND revision = ?",
            (report_id, project_id, revision),
        ).fetchone()
        if report is not None and report["task_id"] in subjects:
            try:
                checks = json.loads(report["checks_json"])
            except (TypeError, json.JSONDecodeError):
                checks = None
            values["qa_status"] = _qa_status(report["status"], checks)
        if node.evidence_ids:
            references = {row[0] for row in connection.execute(
                "SELECT reference FROM project_evidence WHERE project_id = ? AND project_revision = ?", (project_id, revision),
            )}
            values["evidence_status"] = "available" if set(node.evidence_ids) <= references else "unavailable"
        return node.model_copy(update=values)

    @staticmethod
    def _edges(root_id, tasks, nodes, warnings):
        identifiers = {node.id for node in nodes}
        edges = set()
        for task in tasks:
            target = f"task:{task.id}"
            parent = f"task:{task.parent_task_id}" if task.parent_task_id else root_id
            if parent not in identifiers:
                warnings.append(f"Task {task.id}: parent {task.parent_task_id} unavailable")
                parent = root_id
            edges.add((parent, target, "contains"))
            for dependency in task.dependencies:
                source = f"task:{dependency}"
                if source in identifiers:
                    edges.add((source, target, "dependency"))
                else:
                    warnings.append(f"Task {task.id}: dependency {dependency} unavailable")
            for next_task in _strings(task.handoff.get("next_task_ids")):
                next_id = f"task:{next_task}"
                if next_id in identifiers:
                    edges.add((target, next_id, "handoff"))
                else:
                    warnings.append(f"Task {task.id}: handoff target {next_task} unavailable")
        for node in nodes[1:]:
            if node.id.startswith("execution:"):
                edges.add((root_id, node.id, "contains"))
            elif node.id.startswith("planning:"):
                edges.add((root_id, node.id, "contains"))
            elif node.id.startswith(("qa:", "claimlatch:", "memory:")):
                edges.add((root_id, node.id, "contains"))
        return [ProjectMapEdge(source=source, target=target, kind=kind) for source, target, kind in sorted(edges)]

    @staticmethod
    def _agent_edges(agent_graph, nodes, root_id, warnings):
        if not agent_graph:
            return []
        identifiers = {node.id for node in nodes}
        edges = []
        for agent in agent_graph.get("agents", []):
            if not isinstance(agent, Mapping) or not isinstance(agent.get("id"), str):
                continue
            target = f"agent:{agent['id']}"
            if target in identifiers:
                edges.append(ProjectMapEdge(source=root_id, target=target, kind="contains"))
            for dependency in agent.get("dependencies", []):
                source = f"agent:{dependency}"
                if source in identifiers and target in identifiers:
                    edges.append(ProjectMapEdge(source=source, target=target, kind="dependency"))
                else:
                    warnings.append(f"Agent {agent['id']}: dependency {dependency} unavailable")
        return edges

    @staticmethod
    def _depths(nodes, edges, warnings):
        # Topological depth includes hierarchy, dependencies and handoffs.
        # Cycles remain visible, but are reported rather than recursed forever.
        depth = {node.id: 0 if index == 0 else 1 for index, node in enumerate(nodes)}
        parents = {node.id: set() for node in nodes}
        for edge in edges:
            parents[edge.target].add(edge.source)
        remaining = set(depth)
        while remaining:
            ready = sorted(node_id for node_id in remaining if not (parents[node_id] & remaining))
            if not ready:
                warnings.append("Task graph contains a cycle; cyclic node depths are unavailable")
                break
            for node_id in ready:
                if parents[node_id]:
                    depth[node_id] = max(depth[parent] + 1 for parent in parents[node_id])
                remaining.remove(node_id)
        return [node.model_copy(update={"depth": depth[node.id]}) for node in nodes]


def _status(value):
    return _STATUSES.get(value, "unavailable")


def _agent_status(value):
    return {
        "passed": "completed", "completed": "completed", "running": "active",
        "ready": "waiting", "pending": "waiting", "blocked": "blocked", "failed": "failed",
    }.get(value, "waiting")


def _qa_status(status, checks):
    if not isinstance(checks, list):
        return "unavailable"
    statuses = [check.get("status") if isinstance(check, Mapping) and isinstance(check.get("status"), str)
                else None for check in checks]
    if status in {"failed", "FAIL", "FAILED"} or any(item in {"failed", "timeout"} for item in statuses):
        return "FAIL"
    if status in {"passed", "PASS"} and statuses and "passed" in statuses and all(item in {"passed", "skipped"} for item in statuses):
        return "PASS"
    return {"WARN": "WARN", "BLOCK": "BLOCK", "BLOCKED": "BLOCK"}.get(status, "unavailable")


def _string(value):
    return value if isinstance(value, str) and value.strip() else None


def _strings(value):
    return [item for item in value if _string(item)] if isinstance(value, (list, tuple)) else []


def _unique(values):
    return list(dict.fromkeys(values))


def _unique_edges(edges):
    seen = set()
    result = []
    for edge in edges:
        key = (edge.source, edge.target, edge.kind)
        if key not in seen:
            seen.add(key)
            result.append(edge)
    return result
