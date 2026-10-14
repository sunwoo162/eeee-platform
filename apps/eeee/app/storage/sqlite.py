import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from app.design.references import ReferencePack
from app.design.visual_verify import VisualReport
from app.harness.state import AgentTask, ProjectState
from app.domain.errors import AlreadyApprovedError, ApprovalError, CandidateSetChangedError
from app.integrations.claimlatch_audit import ClaimLatchAuditStore
from app.memory.store import MemoryStore
from app.project_runtime.models import ProjectDocumentRecord, ProjectEvidenceRecord, ProjectProfile
from app.planning.models import PlanningArtifact, PlanningDecision, PlanningHandoff, PlanningSession
from app.storage.connection import connect_sqlite
from app.domain.models import (
    CandidateScore,
    Decision,
    PetState,
    Project,
    ReportRecord,
    RequestBrief,
    Run,
    TaskRecord,
)


def _candidate_snapshot(candidates: list[CandidateScore]) -> str:
    return json.dumps(
        [candidate.model_dump(mode="json") for candidate in candidates],
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_or_none(value: str | None) -> dict[str, object] | None:
    return json.loads(value) if value is not None else None


def _project_from_row(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        workspace=row["workspace"],
        revision=row["revision"],
        state=PetState(row["state"]),
        active_task_id=row["active_task_id"],
    )


def _task_from_row(row: sqlite3.Row) -> TaskRecord:
    return TaskRecord(
        id=row["id"],
        project_id=row["project_id"],
        request_id=row["request_id"],
        state=PetState(row["state"]),
        message=row["message"],
        required_action=row["required_action"],
        revision=row["revision"],
        report_id=row["report_id"],
        report=_json_or_none(row["report_json"]),
    )


def _report_from_row(row: sqlite3.Row) -> ReportRecord:
    return ReportRecord(
        id=row["id"],
        project_id=row["project_id"],
        task_id=row["task_id"],
        revision=row["revision"],
        status=row["status"],
        summary=row["summary"],
        checks=json.loads(row["checks_json"]),
    )


def _run_from_row(row: sqlite3.Row, event_jsons: list[str]) -> Run:
    return Run(
        id=row["id"],
        request_id=row["request_id"],
        status=row["status"],
        workspace=row["workspace"],
        events=[json.loads(event_json) for event_json in event_jsons],
        artifacts=json.loads(row["artifacts_json"]),
        error=row["error"],
        created_at=row["created_at"],
    )


def _normalise_run_timestamp(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _run_filter_sql(
    request_id: str | None,
    status: str | None,
    search: str | None,
    created_after: str | None,
    created_before: str | None,
) -> tuple[str, list[object]]:
    filters: list[str] = []
    parameters: list[object] = []
    if request_id is not None:
        filters.append("request_id = ?")
        parameters.append(request_id)
    if status is not None:
        filters.append("status = ?")
        parameters.append(status)
    if search:
        filters.append("(instr(lower(id), lower(?)) > 0 OR instr(lower(request_id), lower(?)) > 0)")
        parameters.extend((search, search))
    if created_after is not None:
        filters.append("utc_timestamp(created_at) >= utc_timestamp(?)")
        parameters.append(created_after)
    if created_before is not None:
        filters.append("utc_timestamp(created_at) <= utc_timestamp(?)")
        parameters.append(created_before)
    where_sql = f" WHERE {' AND '.join(filters)}" if filters else ""
    return where_sql, parameters


def _run_order_sql(sort: str | None, limit: int | None) -> str:
    if sort is None:
        return "rowid ASC" if limit is None else "rowid DESC"
    if sort == "newest":
        return "utc_timestamp(created_at) IS NULL ASC, utc_timestamp(created_at) DESC, rowid DESC"
    if sort == "oldest":
        return "utc_timestamp(created_at) IS NULL ASC, utc_timestamp(created_at) ASC, rowid ASC"
    raise ValueError("sort must be newest or oldest")


def _runs_from_rows(connection: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[Run]:
    if not rows:
        return []
    run_ids = [row["id"] for row in rows]
    events_by_run: dict[str, list[str]] = {run_id: [] for run_id in run_ids}
    for start in range(0, len(run_ids), 500):
        batch = run_ids[start : start + 500]
        placeholders = ", ".join("?" for _ in batch)
        event_rows = connection.execute(
            f"SELECT run_id, event_json FROM run_events WHERE run_id IN ({placeholders}) "
            "ORDER BY run_id, position",
            batch,
        ).fetchall()
        for event_row in event_rows:
            events_by_run[event_row["run_id"]].append(event_row["event_json"])
    return [_run_from_row(row, events_by_run[row["id"]]) for row in rows]


def _load_run(connection: sqlite3.Connection, run_id: str) -> Run:
    row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"Run not found: {run_id}")
    events = connection.execute(
        "SELECT event_json FROM run_events WHERE run_id = ? ORDER BY position", (run_id,)
    ).fetchall()
    return _run_from_row(row, [event["event_json"] for event in events])


def _append_run_events(
    connection: sqlite3.Connection, run_id: str, events: list[dict[str, object]]
) -> None:
    position = connection.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM run_events WHERE run_id = ?", (run_id,)
    ).fetchone()[0]
    for event in events:
        connection.execute(
            "INSERT INTO run_events (run_id, position, event_json) VALUES (?, ?, ?)",
            (run_id, position, json.dumps(event)),
        )
        position += 1


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _lease_now(value: datetime | Callable[[], datetime]) -> datetime:
    return value() if callable(value) else value


@dataclass(frozen=True)
class RunExecutionClaim:
    acquired: bool
    reason: Literal["acquired", "already_running", "expired", "terminal"]
    generation: int
    run: Run


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.claimlatch_audits = ClaimLatchAuditStore(self.path)

    def _connect(self) -> sqlite3.Connection:
        connection = connect_sqlite(self.path)
        connection.row_factory = sqlite3.Row
        connection.create_function("utc_timestamp", 1, _normalise_run_timestamp, deterministic=True)
        return connection

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, brief_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    request_id TEXT NOT NULL, position INTEGER NOT NULL, candidate_json TEXT NOT NULL,
                    PRIMARY KEY (request_id, position)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    request_id TEXT PRIMARY KEY, decision_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decision_events (
                    request_id TEXT NOT NULL, position INTEGER NOT NULL, event_json TEXT NOT NULL,
                    PRIMARY KEY (request_id, position)
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, request_id TEXT NOT NULL, status TEXT NOT NULL,
                    workspace TEXT NOT NULL, artifacts_json TEXT NOT NULL, error TEXT, created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    run_id TEXT NOT NULL, position INTEGER NOT NULL, event_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, position)
                );
                CREATE TABLE IF NOT EXISTS run_execution_leases (
                    run_id TEXT PRIMARY KEY, owner_token TEXT, generation INTEGER NOT NULL, expires_at TEXT
                );
                CREATE TABLE IF NOT EXISTS request_contexts (
                    request_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, workspace TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS harness_states (
                    project_id TEXT PRIMARY KEY, state_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS harness_tasks (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, task_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS design_packs (
                    id TEXT PRIMARY KEY, pack_json TEXT NOT NULL, tokens_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS visual_verifications (
                    id TEXT PRIMARY KEY, url TEXT NOT NULL, baseline TEXT NOT NULL, report_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, workspace TEXT NOT NULL,
                    revision TEXT NOT NULL, state TEXT NOT NULL, active_task_id TEXT
                );
                CREATE TABLE IF NOT EXISTS project_profiles (
                    project_id TEXT PRIMARY KEY, project_revision TEXT NOT NULL,
                    profile_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS planning_sessions (
                    session_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, project_revision TEXT NOT NULL,
                    revision INTEGER NOT NULL, status TEXT NOT NULL, session_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS planning_artifacts (
                    artifact_id TEXT PRIMARY KEY, planning_session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL, project_revision TEXT NOT NULL, artifact_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS planning_decisions (
                    position INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT NOT NULL UNIQUE,
                    planning_session_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    project_revision TEXT NOT NULL, decision_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS planning_handoffs (
                    handoff_id TEXT PRIMARY KEY, planning_session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL, project_revision TEXT NOT NULL, handoff_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_documents (
                    project_id TEXT NOT NULL, provider TEXT NOT NULL,
                    project_revision TEXT NOT NULL, document_json TEXT NOT NULL,
                    PRIMARY KEY (project_id, provider)
                );
                CREATE TABLE IF NOT EXISTS project_evidence (
                    project_id TEXT NOT NULL, evidence_type TEXT NOT NULL,
                    reference TEXT NOT NULL, project_revision TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    PRIMARY KEY (project_id, evidence_type, reference)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    state TEXT NOT NULL, message TEXT NOT NULL, required_action TEXT,
                    revision TEXT NOT NULL, report_id TEXT, report_json TEXT
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    task_id TEXT NOT NULL, position INTEGER NOT NULL, event_json TEXT NOT NULL,
                    PRIMARY KEY (task_id, position)
                );
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    revision TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL,
                    checks_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_envelopes (
                    execution_id TEXT PRIMARY KEY, request_id TEXT NOT NULL,
                    project_id TEXT, project_revision TEXT, capability_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL, status TEXT NOT NULL, envelope_json TEXT NOT NULL,
                    started_at TEXT NOT NULL, completed_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_events (
                    cursor INTEGER PRIMARY KEY AUTOINCREMENT, execution_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, project_id TEXT, project_revision TEXT,
                    event_type TEXT NOT NULL, event_json TEXT NOT NULL, published_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assistant_jobs (
                    job_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, status TEXT NOT NULL,
                    input_json TEXT NOT NULL DEFAULT '{}', result_json TEXT, error TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_activity_events (
                    cursor INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
                    project_revision TEXT NOT NULL, event_json TEXT NOT NULL,
                    event_hash TEXT NOT NULL, occurred_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plugin_registrations (
                    plugin_id TEXT PRIMARY KEY, manifest_version TEXT NOT NULL,
                    status TEXT NOT NULL, manifest_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, removed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS plugin_audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, plugin_id TEXT NOT NULL,
                    action TEXT NOT NULL, status TEXT NOT NULL, manifest_version TEXT NOT NULL,
                    event_json TEXT NOT NULL, occurred_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plugin_installations (
                    plugin_id TEXT PRIMARY KEY, version TEXT NOT NULL,
                    installed_at TEXT NOT NULL, updated_at TEXT NOT NULL, removed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS plugin_connections (
                    user_id TEXT NOT NULL, plugin_id TEXT NOT NULL, status TEXT NOT NULL,
                    approved_permissions_json TEXT NOT NULL, credential_ref TEXT,
                    account_label TEXT, last_health TEXT, last_error TEXT,
                    updated_at TEXT NOT NULL, PRIMARY KEY (user_id, plugin_id)
                );
                """
            )
            run_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
            }
            assistant_job_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(assistant_jobs)").fetchall()
            }
            if "input_json" not in assistant_job_columns:
                connection.execute("ALTER TABLE assistant_jobs ADD COLUMN input_json TEXT NOT NULL DEFAULT '{}'")
            if "lease_owner" not in assistant_job_columns:
                connection.execute("ALTER TABLE assistant_jobs ADD COLUMN lease_owner TEXT")
            if "lease_expires_at" not in assistant_job_columns:
                connection.execute("ALTER TABLE assistant_jobs ADD COLUMN lease_expires_at TEXT")
            if "error" not in run_columns:
                connection.execute("ALTER TABLE runs ADD COLUMN error TEXT")
            if "created_at" not in run_columns:
                connection.execute("ALTER TABLE runs ADD COLUMN created_at TEXT")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_request_id ON runs (request_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs (status)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs (created_at)")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_execution_envelopes_project_revision "
                "ON execution_envelopes (project_id, project_revision, started_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_execution_events_project_cursor "
                "ON execution_events (project_id, project_revision, cursor)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_plugin_registrations_status "
                "ON plugin_registrations (status, removed_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_plugin_audit_events_plugin "
                "ON plugin_audit_events (plugin_id, id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_plugin_connections_user "
                "ON plugin_connections (user_id, plugin_id)"
            )
        # EEEE memory intentionally shares the durable state database so a
        # restart cannot separate project state from the evidence-backed memory.
        MemoryStore(self.path).init()
        # ClaimLatch audit evidence lives beside project state and memory so
        # verification cannot silently disappear between local restarts.
        self.claimlatch_audits.init()

    def save_request(self, brief: RequestBrief) -> str:
        request_id = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO requests (id, brief_json) VALUES (?, ?)",
                (request_id, brief.model_dump_json()),
            )
        return request_id

    def get_request(self, request_id: str) -> RequestBrief:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT brief_json FROM requests WHERE id = ?", (request_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Request not found: {request_id}")
        return RequestBrief.model_validate_json(row["brief_json"])

    def save_request_context(self, request_id: str, project_id: str, workspace: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO request_contexts (request_id, project_id, workspace) VALUES (?, ?, ?)",
                (request_id, project_id, workspace),
            )

    def get_request_context(self, request_id: str) -> tuple[str, str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT project_id, workspace FROM request_contexts WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Request context not found: {request_id}")
        return row["project_id"], row["workspace"]

    def get_latest_request_context_for_project(self, project_id: str) -> tuple[str, str] | None:
        """Return the durable request identity already allocated to a project.

        Background project execution can be restarted after provisioning has
        begun.  Reusing this context prevents a retry from creating another
        request/task for the same project.
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_id, workspace FROM request_contexts "
                "WHERE project_id = ? ORDER BY rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        return row["request_id"], row["workspace"]

    def save_harness_state(self, project_id: str, state: ProjectState) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO harness_states (project_id, state_json) VALUES (?, ?) "
                "ON CONFLICT(project_id) DO UPDATE SET state_json = excluded.state_json",
                (project_id, state.model_dump_json()),
            )

    def get_harness_state(self, project_id: str) -> ProjectState:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM harness_states WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Harness state not found: {project_id}")
        return ProjectState.model_validate_json(row["state_json"])

    def save_harness_task(self, project_id: str, task: AgentTask) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO harness_tasks (id, project_id, task_json) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET project_id = excluded.project_id, "
                "task_json = excluded.task_json",
                (task.id, project_id, task.model_dump_json()),
            )
            revision = task.project_revision
            if revision is None:
                revision = connection.execute(
                    "SELECT revision FROM projects WHERE id = ?", (project_id,)
                ).fetchone()
                revision = revision[0] if revision is not None else None
            if revision is not None:
                self._append_project_map_event(
                    connection, project_id, revision,
                    {"eventType": "task.lifecycle", "executionId": task.id,
                     "requestId": task.id, "projectId": project_id,
                     "projectRevision": revision,
                     "payload": {"source": "harness", "taskId": task.id,
                                  "status": task.status},
                     "publishedAt": datetime.now(timezone.utc).isoformat()},
                )

    def get_harness_task(self, task_id: str) -> AgentTask:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT task_json FROM harness_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Harness task not found: {task_id}")
        return AgentTask.model_validate_json(row["task_json"])

    def save_design_pack(
        self, pack_id: str, pack: ReferencePack, tokens: dict[str, object]
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO design_packs (id, pack_json, tokens_json) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET pack_json = excluded.pack_json, "
                "tokens_json = excluded.tokens_json",
                (pack_id, pack.model_dump_json(), json.dumps(tokens)),
            )

    def get_design_pack(self, pack_id: str) -> tuple[ReferencePack, dict[str, object]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT pack_json, tokens_json FROM design_packs WHERE id = ?", (pack_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Design reference pack not found: {pack_id}")
        return ReferencePack.model_validate_json(row["pack_json"]), json.loads(row["tokens_json"])

    def save_visual_verification(
        self, verification_id: str, url: str, baseline: str, report: VisualReport
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO visual_verifications (id, url, baseline, report_json) VALUES (?, ?, ?, ?)",
                (verification_id, url, baseline, report.model_dump_json()),
            )

    def get_visual_verification(
        self, verification_id: str
    ) -> tuple[str, str, VisualReport]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT url, baseline, report_json FROM visual_verifications WHERE id = ?",
                (verification_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Visual verification not found: {verification_id}")
        return row["url"], row["baseline"], VisualReport.model_validate_json(row["report_json"])

    def save_candidates(self, request_id: str, candidates: list[CandidateScore]) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT decision_json FROM decisions WHERE request_id = ?", (request_id,)
            ).fetchone()
            if row and Decision.model_validate_json(row["decision_json"]).approved:
                raise AlreadyApprovedError(f"Decision already approved: {request_id}")
            connection.execute("DELETE FROM candidates WHERE request_id = ?", (request_id,))
            connection.executemany(
                "INSERT INTO candidates (request_id, position, candidate_json) VALUES (?, ?, ?)",
                [(request_id, index, candidate.model_dump_json()) for index, candidate in enumerate(candidates)],
            )

    def get_candidates(self, request_id: str) -> list[CandidateScore]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT candidate_json FROM candidates WHERE request_id = ? ORDER BY position",
                (request_id,),
            ).fetchall()
        return [CandidateScore.model_validate_json(row["candidate_json"]) for row in rows]

    def create_project(
        self, project_id: str, name: str, workspace: str, revision: str = "initial"
    ) -> Project:
        project = Project(
            id=project_id,
            name=name,
            workspace=workspace,
            revision=revision,
            state=PetState.idle,
            active_task_id=None,
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO projects (id, name, workspace, revision, state, active_task_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (project.id, project.name, project.workspace, project.revision, project.state.value, None),
            )
        return project

    def get_project(self, project_id: str) -> Project:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Project not found: {project_id}")
        return _project_from_row(row)

    def save_project_profile(self, profile: ProjectProfile) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO project_profiles (project_id, project_revision, profile_json) "
                "VALUES (?, ?, ?) ON CONFLICT(project_id) DO UPDATE SET "
                "project_revision = excluded.project_revision, profile_json = excluded.profile_json",
                (profile.project_id, profile.project_revision, profile.model_dump_json()),
            )

    def get_project_profile(self, project_id: str) -> ProjectProfile:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT profile_json FROM project_profiles WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Project profile not found: {project_id}")
        return ProjectProfile.model_validate_json(row["profile_json"])

    def _ensure_planning_revision(self, project_id: str, project_revision: str) -> None:
        from app.runtime.store import StaleProjectRevision

        with self._connect() as connection:
            row = connection.execute("SELECT revision FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"Project not found: {project_id}")
        if row["revision"] != project_revision:
            raise StaleProjectRevision(f"stale project revision for {project_id}: {project_revision}")

    def _ensure_activity_revision(self, project_id: str, project_revision: str) -> None:
        self._ensure_planning_revision(project_id, project_revision)

    def save_planning_session(self, session: PlanningSession) -> None:
        self._ensure_planning_revision(session.project_id, session.project_revision)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO planning_sessions "
                "(session_id, project_id, project_revision, revision, status, session_json) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET "
                "revision = excluded.revision, status = excluded.status, session_json = excluded.session_json",
                (
                    session.session_id, session.project_id, session.project_revision,
                    session.revision, session.status, session.model_dump_json(),
                ),
            )

    def get_planning_session(self, session_id: str) -> PlanningSession:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT session_json FROM planning_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Planning session not found: {session_id}")
        return PlanningSession.model_validate_json(row["session_json"])

    def list_planning_sessions(self, project_id: str, project_revision: str) -> list[PlanningSession]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT session_json FROM planning_sessions WHERE project_id = ? AND project_revision = ? "
                "ORDER BY rowid", (project_id, project_revision),
            ).fetchall()
        return [PlanningSession.model_validate_json(row["session_json"]) for row in rows]

    def save_planning_artifact(self, artifact: PlanningArtifact) -> None:
        self._ensure_planning_revision(artifact.project_id, artifact.project_revision)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO planning_artifacts "
                "(artifact_id, planning_session_id, project_id, project_revision, artifact_json) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(artifact_id) DO UPDATE SET artifact_json = excluded.artifact_json",
                (
                    artifact.artifact_id, artifact.planning_session_id, artifact.project_id,
                    artifact.project_revision, artifact.model_dump_json(),
                ),
            )

    def list_planning_artifacts(self, session_id: str) -> list[PlanningArtifact]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT artifact_json FROM planning_artifacts WHERE planning_session_id = ? ORDER BY artifact_id",
                (session_id,),
            ).fetchall()
        return [PlanningArtifact.model_validate_json(row["artifact_json"]) for row in rows]

    def append_planning_decision(self, decision: PlanningDecision) -> None:
        self._ensure_planning_revision(decision.project_id, decision.project_revision)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO planning_decisions "
                "(decision_id, planning_session_id, project_id, project_revision, decision_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    decision.decision_id, decision.planning_session_id, decision.project_id,
                    decision.project_revision, decision.model_dump_json(),
                ),
            )

    def list_planning_decisions(self, session_id: str) -> list[PlanningDecision]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT decision_json FROM planning_decisions "
                "WHERE planning_session_id = ? ORDER BY position", (session_id,),
            ).fetchall()
        return [PlanningDecision.model_validate_json(row["decision_json"]) for row in rows]

    def save_planning_handoff(self, handoff: PlanningHandoff) -> None:
        self._ensure_planning_revision(handoff.project_id, handoff.project_revision)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO planning_handoffs "
                "(handoff_id, planning_session_id, project_id, project_revision, handoff_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    handoff.handoff_id, handoff.planning_session_id, handoff.project_id,
                    handoff.project_revision, handoff.model_dump_json(),
                ),
            )

    def get_planning_handoff(self, handoff_id: str) -> PlanningHandoff:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT handoff_json FROM planning_handoffs WHERE handoff_id = ?", (handoff_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Planning handoff not found: {handoff_id}")
        return PlanningHandoff.model_validate_json(row["handoff_json"])

    def save_project_document(self, document: ProjectDocumentRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO project_documents "
                "(project_id, provider, project_revision, document_json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(project_id, provider) DO UPDATE SET "
                "project_revision = excluded.project_revision, document_json = excluded.document_json",
                (
                    document.project_id,
                    document.provider,
                    document.project_revision,
                    document.model_dump_json(),
                ),
            )

    def get_project_document(self, project_id: str, provider: str) -> ProjectDocumentRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document_json FROM project_documents WHERE project_id = ? AND provider = ?",
                (project_id, provider),
            ).fetchone()
        if row is None:
            raise KeyError(f"Project document not found: {project_id}/{provider}")
        return ProjectDocumentRecord.model_validate_json(row["document_json"])

    def save_project_evidence(self, evidence: ProjectEvidenceRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO project_evidence "
                "(project_id, evidence_type, reference, project_revision, evidence_json) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(project_id, evidence_type, reference) DO UPDATE SET "
                "project_revision = excluded.project_revision, evidence_json = excluded.evidence_json",
                (
                    evidence.project_id,
                    evidence.evidence_type,
                    evidence.reference,
                    evidence.project_revision,
                    evidence.model_dump_json(),
                ),
            )

    def get_project_evidence(
        self, project_id: str, evidence_type: str, reference: str
    ) -> ProjectEvidenceRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT evidence_json FROM project_evidence "
                "WHERE project_id = ? AND evidence_type = ? AND reference LIKE ?",
                (project_id, evidence_type, f"%:{reference}"),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT evidence_json FROM project_evidence "
                    "WHERE project_id = ? AND evidence_type = ? AND json_extract(evidence_json, '$.payload.headSha') = ?",
                    (project_id, evidence_type, reference),
                ).fetchone()
        if row is None:
            raise KeyError(f"Project evidence not found: {project_id}/{evidence_type}/{reference}")
        return ProjectEvidenceRecord.model_validate_json(row["evidence_json"])

    def update_project_revision(self, project_id: str, revision: str) -> Project:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE projects SET revision = ? WHERE id = ?", (revision, project_id)
            )
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Project not found: {project_id}")
        return _project_from_row(row)

    def update_project_state(
        self, project_id: str, state: PetState, active_task_id: str | None = None
    ) -> Project:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE projects SET state = ?, active_task_id = ? WHERE id = ?",
                (state.value, active_task_id, project_id),
            )
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Project not found: {project_id}")
        return _project_from_row(row)

    def create_task(self, project_id: str, request_id: str, revision: str) -> TaskRecord:
        task = TaskRecord(
            id=str(uuid4()),
            project_id=project_id,
            request_id=request_id,
            state=PetState.researching,
            message="Researching request",
            required_action=None,
            revision=revision,
            report_id=None,
            report=None,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO tasks (id, project_id, request_id, state, message, required_action, "
                "revision, report_id, report_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    task.project_id,
                    task.request_id,
                    task.state.value,
                    task.message,
                    task.required_action,
                    task.revision,
                    task.report_id,
                    None,
                ),
            )
            connection.execute(
                "UPDATE projects SET state = ?, active_task_id = ? WHERE id = ?",
                (task.state.value, task.id, project_id),
            )
            self._append_project_map_event(
                connection, project_id, revision,
                {"eventType": "task.lifecycle", "executionId": task.id,
                 "requestId": task.request_id, "projectId": project_id,
                 "projectRevision": revision,
                 "payload": {"source": "coordinator", "taskId": task.id,
                              "status": task.state.value},
                 "publishedAt": datetime.now(timezone.utc).isoformat()},
            )
        return task

    def get_task(self, task_id: str) -> TaskRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Task not found: {task_id}")
        return _task_from_row(row)

    def update_task(
        self,
        task_id: str,
        state: PetState,
        message: str,
        required_action: str | None = None,
        revision: str | None = None,
        report_id: str | None = None,
        report: dict[str, object] | None = None,
    ) -> TaskRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if current is None:
                raise KeyError(f"Task not found: {task_id}")
            task = TaskRecord(
                id=current["id"],
                project_id=current["project_id"],
                request_id=current["request_id"],
                state=state,
                message=message,
                required_action=required_action,
                revision=revision if revision is not None else current["revision"],
                report_id=report_id if report_id is not None else current["report_id"],
                report=report if report is not None else _json_or_none(current["report_json"]),
            )
            connection.execute(
                "UPDATE tasks SET state = ?, message = ?, required_action = ?, revision = ?, "
                "report_id = ?, report_json = ? WHERE id = ?",
                (
                    task.state.value,
                    task.message,
                    task.required_action,
                    task.revision,
                    task.report_id,
                    json.dumps(task.report) if task.report is not None else None,
                    task.id,
                ),
            )
            connection.execute(
                "UPDATE projects SET state = ?, active_task_id = ? WHERE id = ?",
                (task.state.value, task.id, task.project_id),
            )
            self._append_project_map_event(
                connection, task.project_id, task.revision,
                {"eventType": "task.lifecycle", "executionId": task.id,
                 "requestId": task.request_id, "projectId": task.project_id,
                 "projectRevision": task.revision,
                 "payload": {"source": "coordinator", "taskId": task.id,
                              "status": task.state.value},
                 "publishedAt": datetime.now(timezone.utc).isoformat()},
            )
        return task

    @staticmethod
    def _append_project_map_event(connection: sqlite3.Connection, project_id: str,
                                   project_revision: str, event: dict[str, object]) -> int:
        cursor = connection.execute(
            "INSERT INTO execution_events "
            "(execution_id, request_id, project_id, project_revision, event_type, event_json, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event["executionId"], event["requestId"], project_id, project_revision,
             event["eventType"], json.dumps(event), event["publishedAt"]),
        ).lastrowid
        published = {**event, "cursor": cursor}
        connection.execute(
            "UPDATE execution_events SET event_json = ? WHERE cursor = ?",
            (json.dumps(published), cursor),
        )
        return cursor

    def append_task_event(self, task_id: str, event: dict[str, object]) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM task_events WHERE task_id = ?",
                (task_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO task_events (task_id, position, event_json) VALUES (?, ?, ?)",
                (task_id, position, json.dumps(event)),
            )

    def get_task_events(self, task_id: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_json FROM task_events WHERE task_id = ? ORDER BY position",
                (task_id,),
            ).fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    def save_report(self, report: ReportRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO reports (id, project_id, task_id, revision, status, summary, checks_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    report.id,
                    report.project_id,
                    report.task_id,
                    report.revision,
                    report.status,
                    report.summary,
                    json.dumps(report.checks),
                ),
            )

    def get_report(self, report_id: str) -> ReportRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM reports WHERE id = ?", (report_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Report not found: {report_id}")
        return _report_from_row(row)

    def save_decision(self, decision: Decision) -> None:
        if decision.approved:
            raise ApprovalError("Direct approval must be recorded through ApprovalService")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT decision_json FROM decisions WHERE request_id = ?", (decision.request_id,)
            ).fetchone()
            if row and Decision.model_validate_json(row["decision_json"]).approved:
                raise AlreadyApprovedError(f"Decision already approved: {decision.request_id}")
            connection.execute(
                "INSERT INTO decisions (request_id, decision_json) VALUES (?, ?) "
                "ON CONFLICT(request_id) DO UPDATE SET decision_json = excluded.decision_json",
                (decision.request_id, decision.model_dump_json()),
            )

    def get_decision(self, request_id: str) -> Decision | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT decision_json FROM decisions WHERE request_id = ?", (request_id,)
            ).fetchone()
        return Decision.model_validate_json(row["decision_json"]) if row else None

    def get_decision_events(self, request_id: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_json FROM decision_events WHERE request_id = ? ORDER BY position",
                (request_id,),
            ).fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    def save_approval_once(
        self, decision: Decision, event: dict[str, object], expected_candidates: list[CandidateScore]
    ) -> bool:
        """Atomically store an approval and audit event unless already approved."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT decision_json FROM decisions WHERE request_id = ?", (decision.request_id,)
            ).fetchone()
            if row and Decision.model_validate_json(row["decision_json"]).approved:
                return False
            candidate_rows = connection.execute(
                "SELECT candidate_json FROM candidates WHERE request_id = ? ORDER BY position",
                (decision.request_id,),
            ).fetchall()
            current_candidates = [
                CandidateScore.model_validate_json(row["candidate_json"])
                for row in candidate_rows
            ]
            if _candidate_snapshot(current_candidates) != _candidate_snapshot(expected_candidates):
                raise CandidateSetChangedError(
                    f"Approval candidate set changed for decision: {decision.request_id}"
                )
            connection.execute(
                "INSERT INTO decisions (request_id, decision_json) VALUES (?, ?) "
                "ON CONFLICT(request_id) DO UPDATE SET decision_json = excluded.decision_json",
                (decision.request_id, decision.model_dump_json()),
            )
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM decision_events WHERE request_id = ?",
                (decision.request_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO decision_events (request_id, position, event_json) VALUES (?, ?, ?)",
                (decision.request_id, position, json.dumps(event)),
            )
        return True
    def create_run(self, request_id: str, workspace: str) -> Run:
        run = Run(
            id=str(uuid4()),
            request_id=request_id,
            status="created",
            workspace=workspace,
            events=[],
            artifacts=[],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs (id, request_id, status, workspace, artifacts_json, error, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run.id, run.request_id, run.status, run.workspace, json.dumps(run.artifacts), run.error, run.created_at),
            )
        return run

    def update_run(
        self,
        run_id: str,
        *,
        status: str,
        artifacts: list[dict[str, object]],
        error: str | None,
    ) -> Run:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE runs SET status = ?, artifacts_json = ?, error = ? WHERE id = ?",
                (status, json.dumps(artifacts), error, run_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Run not found: {run_id}")
        return self.get_run(run_id)

    def claim_run_execution(
        self, run_id: str, owner_token: str,
        now: datetime | Callable[[], datetime], lease_seconds: int = 60,
    ) -> RunExecutionClaim:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sampled_now = _lease_now(now)
            now_iso = _utc_iso(sampled_now)
            expires_at = _utc_iso(sampled_now + timedelta(seconds=lease_seconds))
            run_row = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run_row is None:
                raise KeyError(f"Run not found: {run_id}")
            lease = connection.execute(
                "SELECT owner_token, generation, expires_at FROM run_execution_leases WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            generation = lease["generation"] if lease is not None else 0

            if run_row["status"] == "running":
                lease_expiry = (
                    _normalise_run_timestamp(lease["expires_at"])
                    if lease is not None else None
                )
                if (
                    lease is not None
                    and lease["owner_token"] is not None
                    and lease_expiry is not None
                    and lease_expiry > _normalise_run_timestamp(now_iso)
                ):
                    return RunExecutionClaim(False, "already_running", generation, _load_run(connection, run_id))

                warning = (
                    "Execution lease expired. Check the workspace for partial changes before retrying."
                    if lease is not None and lease["owner_token"] is not None
                    else "Execution ownership was lost. Check the workspace for partial changes before retrying."
                )
                event_type = "execution_expired" if lease is not None and lease["owner_token"] is not None else "execution_stale"
                generation += 1
                connection.execute(
                    "INSERT INTO run_execution_leases (run_id, owner_token, generation, expires_at) "
                    "VALUES (?, NULL, ?, NULL) ON CONFLICT(run_id) DO UPDATE SET "
                    "owner_token = NULL, generation = excluded.generation, expires_at = NULL",
                    (run_id, generation),
                )
                connection.execute(
                    "UPDATE runs SET status = 'failed', error = ? WHERE id = ?", (warning, run_id)
                )
                _append_run_events(connection, run_id, [{"type": event_type, "message": warning}])
                return RunExecutionClaim(False, "expired", generation, _load_run(connection, run_id))

            if run_row["status"] != "created":
                return RunExecutionClaim(False, "terminal", generation, _load_run(connection, run_id))

            generation += 1
            connection.execute(
                "INSERT INTO run_execution_leases (run_id, owner_token, generation, expires_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET "
                "owner_token = excluded.owner_token, generation = excluded.generation, "
                "expires_at = excluded.expires_at",
                (run_id, owner_token, generation, expires_at),
            )
            connection.execute("UPDATE runs SET status = 'running' WHERE id = ?", (run_id,))
            return RunExecutionClaim(True, "acquired", generation, _load_run(connection, run_id))

    def renew_run_execution(
        self, run_id: str, owner_token: str, generation: int,
        now: datetime | Callable[[], datetime],
        lease_seconds: int = 60,
    ) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sampled_now = _lease_now(now)
            now_iso = _utc_iso(sampled_now)
            expires_at = _utc_iso(sampled_now + timedelta(seconds=lease_seconds))
            cursor = connection.execute(
                "UPDATE run_execution_leases SET expires_at = "
                "CASE WHEN utc_timestamp(expires_at) > utc_timestamp(?) "
                "THEN expires_at ELSE ? END WHERE run_id = ? "
                "AND owner_token = ? AND generation = ? "
                "AND utc_timestamp(expires_at) > utc_timestamp(?) "
                "AND EXISTS (SELECT 1 FROM runs WHERE id = ? AND status = 'running')",
                (expires_at, expires_at, run_id, owner_token, generation, now_iso, run_id),
            )
            return cursor.rowcount == 1

    def complete_run_execution(
        self, run_id: str, owner_token: str, generation: int, status: str,
        events: list[dict[str, object]], artifacts: list[dict[str, object]],
        error: str | None, now: datetime | Callable[[], datetime],
    ) -> Run | None:
        if status not in {"completed", "failed", "unavailable"}:
            raise ValueError(f"run execution completion status must be terminal: {status}")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now_iso = _utc_iso(_lease_now(now))
            lease = connection.execute(
                "SELECT 1 FROM run_execution_leases WHERE run_id = ? AND owner_token = ? "
                "AND generation = ? AND utc_timestamp(expires_at) > utc_timestamp(?) "
                "AND EXISTS (SELECT 1 FROM runs WHERE id = ? AND status = 'running')",
                (run_id, owner_token, generation, now_iso, run_id),
            ).fetchone()
            if lease is None:
                return None
            _append_run_events(connection, run_id, events)
            connection.execute(
                "UPDATE runs SET status = ?, artifacts_json = ?, error = ? WHERE id = ?",
                (status, json.dumps(artifacts), error, run_id),
            )
            connection.execute(
                "UPDATE run_execution_leases SET owner_token = NULL, expires_at = NULL "
                "WHERE run_id = ? AND owner_token = ? AND generation = ?",
                (run_id, owner_token, generation),
            )
            return _load_run(connection, run_id)

    def reset_run_for_retry(self, run_id: str) -> Run:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run_row is None:
                raise KeyError(f"Run not found: {run_id}")
            if run_row["status"] not in {"failed", "unavailable"}:
                raise ApprovalError("Only failed or unavailable runs can be retried")
            connection.execute(
                "INSERT INTO run_execution_leases (run_id, owner_token, generation, expires_at) "
                "VALUES (?, NULL, 1, NULL) ON CONFLICT(run_id) DO UPDATE SET "
                "owner_token = NULL, generation = generation + 1, expires_at = NULL",
                (run_id,),
            )
            connection.execute(
                "UPDATE runs SET status = 'created', artifacts_json = '[]', error = NULL WHERE id = ?",
                (run_id,),
            )
            _append_run_events(
                connection, run_id,
                [{"type": "retry_requested", "previous_status": run_row["status"]}],
            )
            return _load_run(connection, run_id)

    def get_run_for_request(self, request_id: str) -> Run:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM runs WHERE request_id = ? ORDER BY rowid DESC LIMIT 1",
                (request_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Run not found for request: {request_id}")
        return self.get_run(row["id"])

    def list_runs(
        self,
        request_id: str | None = None,
        *,
        status: str | None = None,
        search: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Run]:
        where_sql, parameters = _run_filter_sql(
            request_id, status, search, created_after, created_before
        )
        order = _run_order_sql(sort, limit)
        query = f"SELECT * FROM runs{where_sql} ORDER BY {order}"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            parameters.extend((limit, offset))
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return _runs_from_rows(connection, rows)

    def list_runs_with_count(
        self,
        request_id: str | None = None,
        *,
        status: str | None = None,
        search: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[Run], int]:
        where_sql, count_parameters = _run_filter_sql(
            request_id, status, search, created_after, created_before
        )
        list_parameters = [*count_parameters]
        order = _run_order_sql(sort, limit)
        query = f"SELECT * FROM runs{where_sql} ORDER BY {order}"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            list_parameters.extend((limit, offset))
        with self._connect() as connection:
            connection.execute("BEGIN")
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM runs{where_sql}", count_parameters
                ).fetchone()[0]
            )
            rows = connection.execute(query, list_parameters).fetchall()
            runs = _runs_from_rows(connection, rows)
        return runs, total

    def count_runs(
        self,
        request_id: str | None = None,
        *,
        status: str | None = None,
        search: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
    ) -> int:
        where_sql, parameters = _run_filter_sql(
            request_id, status, search, created_after, created_before
        )
        with self._connect() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM runs{where_sql}", parameters).fetchone()[0])

    def append_event(self, run_id: str, event: dict[str, object]) -> None:
        with self._connect() as connection:
            # Reserve the writer slot before reading the next position.
            connection.execute("BEGIN IMMEDIATE")
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM run_events WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO run_events (run_id, position, event_json) VALUES (?, ?, ?)",
                (run_id, position, json.dumps(event)),
            )

    def get_run(self, run_id: str) -> Run:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"Run not found: {run_id}")
            event_rows = connection.execute(
                "SELECT event_json FROM run_events WHERE run_id = ? ORDER BY position", (run_id,)
            ).fetchall()
        return _run_from_row(row, [event["event_json"] for event in event_rows])
