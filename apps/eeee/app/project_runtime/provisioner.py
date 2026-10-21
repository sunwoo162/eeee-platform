from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from app.domain.models import Project, RequestBrief
from app.project_runtime.connectors import PlanningConnector, ProjectConnector, build_default_connectors
from app.project_runtime.models import ProjectProfile, ProjectProvisioningResult
from app.project_runtime.scaffold import create_todo_scaffold
from app.project_runtime.web_scaffold import create_web_app_scaffold
from app.project_runtime.web_runner import WebProjectRunner
from app.project_runtime.iseol_bridge import IseolPlanBridge
from app.planning.models import PlanningHandoff
from app.project_runtime.todo_runner import TodoProjectRunner
from app.iseol.contracts import ProjectIntent
from app.project_runtime.meal_planner_scaffold import MealPlannerTemplate
from app.project_runtime.templates import WebTemplateCatalog
import json
from datetime import datetime, timezone
from app.storage.sqlite import SQLiteStore


class ProjectProvisioner:
    """Create the durable local representation of one unified Project Runtime."""

    def __init__(
        self,
        store: SQLiteStore,
        connectors: Mapping[str, ProjectConnector] | None = None,
        configured_connector_ids: Callable[[], set[str]] | None = None,
        iseol_bridge: IseolPlanBridge | None = None,
        todo_runner: TodoProjectRunner | None = None,
        web_runner: WebProjectRunner | None = None,
    ) -> None:
        self.store = store
        self.connectors = dict(connectors or build_default_connectors())
        self.configured_connector_ids = configured_connector_ids
        self.iseol_bridge = iseol_bridge
        self.todo_runner = todo_runner or TodoProjectRunner()
        self.web_runner = web_runner or WebProjectRunner()

    def provision(
        self,
        project: Project,
        request: RequestBrief,
        *,
        memory_ids: list[str],
        qa_baseline_ids: list[str],
        memory_context: list[dict[str, object]] | None = None,
        request_id: str | None = None,
        planning_handoff: PlanningHandoff | None = None,
        intent: ProjectIntent | None = None,
    ) -> ProjectProvisioningResult:
        existing = self._existing_current_profile(project)
        if existing is not None:
            self._create_scaffold(project.workspace, project.name, request, intent, existing.template_id)
            execution_plan_path = self._write_execution_plan(
                project, request, memory_ids, qa_baseline_ids, memory_context, request_id, planning_handoff,
                intent=intent,
            )
            return _result(existing, execution_plan_path=execution_plan_path)

        Path(project.workspace).mkdir(parents=True, exist_ok=True)
        self._create_scaffold(project.workspace, project.name, request, intent)
        profile = ProjectProfile(
            project_id=project.id,
            project_revision=project.revision,
            goal=request.goal,
            template_id=intent.template_id if intent is not None else None,
            assumptions=list(intent.assumptions) if intent is not None else [],
            runtime_profile=("web_app" if request.target_type == "web_app" else request.runtime_profile),
            scope=[request.target_type, *request.acceptance_criteria],
            constraints=list(request.constraints),
            acceptance_criteria=list(request.acceptance_criteria),
            workspace=project.workspace,
            capabilities=["project-execution"],
            schedule={},
            preferences={},
            memory_ids=list(memory_ids),
            qa_baseline_ids=list(qa_baseline_ids),
            connectors=[],
            provenance={
                "goal": "user_request",
                "scope": "request_parser",
                "connectors": "local_connector_registry",
            },
        )
        configured = set(self.configured_connector_ids() if self.configured_connector_ids else ())
        bindings = [
            _plan_connector(connector, profile, configured)
            for connector in self.connectors.values()
        ]
        profile = profile.model_copy(update={"connectors": bindings})
        self.store.save_project_profile(profile)
        self._write_local_project_documents(profile, request, planning_handoff)
        execution_plan_path = None
        execution_plan_path = self._write_execution_plan(
            project, request, memory_ids, qa_baseline_ids, memory_context, request_id, planning_handoff,
            intent=intent,
        )
        return _result(profile, execution_plan_path=execution_plan_path)

    @staticmethod
    def _create_scaffold(
        workspace: str,
        project_name: str,
        request: RequestBrief,
        intent: ProjectIntent | None,
        existing_template_id: str | None = None,
    ) -> None:
        template_id = intent.template_id if intent is not None else existing_template_id
        if template_id == "meal_planner":
            MealPlannerTemplate.create(Path(workspace), project_name)
        elif template_id == "todo_app":
            if request.runtime_profile == "web_app" and _contains_web_marker(request.raw_text):
                create_web_app_scaffold(workspace, project_name)
            else:
                create_todo_scaffold(workspace)
        elif _is_todo_request(request.goal, [request.target_type, *request.acceptance_criteria]):
            create_todo_scaffold(workspace)
        elif intent is not None and WebTemplateCatalog.resolve(intent).id == "generic_web":
            create_web_app_scaffold(workspace, project_name)
        elif _is_web_request(request):
            create_web_app_scaffold(workspace, project_name)

    @staticmethod
    def _write_local_project_documents(
        profile: ProjectProfile,
        request: RequestBrief,
        planning_handoff: PlanningHandoff | None,
    ) -> None:
        root = Path(profile.workspace)
        (root / "PROJECT_PROFILE.json").write_text(
            json.dumps(profile.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        handoff = planning_handoff.handoff_id if planning_handoff is not None else "not-created"
        lines = [
            "# Project Log",
            "",
            f"- Project: `{profile.project_id}`",
            f"- Revision: `{profile.project_revision}`",
            f"- Created: `{datetime.now(timezone.utc).isoformat()}`",
            f"- Request: {request.goal}",
            f"- Planning handoff: `{handoff}`",
            "",
            "## Acceptance criteria",
            *[f"- {item}" for item in profile.acceptance_criteria],
            "",
            "## Record policy",
            "This local record is the source of truth until an optional document connector is configured.",
            "QA_REPORT.json, RELEASE_MANIFEST.json, execution-plan.json, and Git history are linked evidence.",
            "Rollback policy: restore the previous RELEASE_MANIFEST.json and Git revision, then record the result.",
            f"Template: `{profile.template_id or 'legacy'}`",
        ]
        (root / "PROJECT_LOG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_execution_plan(
        self,
        project: Project,
        request: RequestBrief,
        memory_ids: list[str],
        qa_baseline_ids: list[str],
        memory_context: list[dict[str, object]] | None,
        request_id: str | None,
        planning_handoff: PlanningHandoff | None,
        *,
        intent: ProjectIntent | None = None,
    ) -> str | None:
        if self.iseol_bridge is None or request_id is None:
            return None
        plan = self.iseol_bridge.create_plan(
            project_id=project.id,
            project_revision=project.revision,
            request_id=request_id,
            request=request,
            memory_ids=memory_ids,
            qa_baseline_ids=qa_baseline_ids,
            memory_context=memory_context,
            planning_handoff=planning_handoff,
            intent=intent,
        )
        plan_path = Path(project.workspace) / "execution-plan.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return str(plan_path)

    def _existing_current_profile(self, project: Project) -> ProjectProfile | None:
        try:
            profile = self.store.get_project_profile(project.id)
        except KeyError:
            return None
        if profile.project_revision != project.revision:
            raise ValueError(
                "Cannot reuse a project profile from a different revision: "
                f"{profile.project_revision} != {project.revision}"
            )
        return profile


def _result(profile: ProjectProfile, *, execution_plan_path: str | None = None) -> ProjectProvisioningResult:
    missing = sorted(
        binding.connector_id
        for binding in profile.connectors
        if binding.state == "awaiting_configuration"
    )
    return ProjectProvisioningResult(profile=profile, missing_connectors=missing, execution_plan_path=execution_plan_path)


def _plan_connector(
    connector: ProjectConnector,
    profile: ProjectProfile,
    configured_connector_ids: set[str],
) -> ConnectorBinding:
    if isinstance(connector, PlanningConnector) and connector.connector_id in configured_connector_ids:
        connector = replace(connector, configured=True)
    return connector.plan(profile)


def _is_todo_request(goal: str, scope: list[str]) -> bool:
    text = " ".join([goal, *scope]).lower()
    return "todo" in text or "할 일" in text or "체크리스트" in text


def is_todo_request(goal: str, scope: list[str]) -> bool:
    return _is_todo_request(goal, scope)


def _is_web_request(request: RequestBrief) -> bool:
    return request.target_type == "web_app" or request.runtime_profile == "web_app"


def _contains_web_marker(text: str) -> bool:
    folded = text.casefold()
    return any(marker in folded for marker in ("웹", "website", "web app", "webapp", "홈페이지", "사이트"))

