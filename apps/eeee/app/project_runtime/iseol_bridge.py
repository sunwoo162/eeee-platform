from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.domain.models import RequestBrief
from app.integrations.contracts import ProjectBriefV1
from app.iseol.contracts import ProjectIntent
from app.iseol.extensions import ExtensionManifest, ExtensionRegistry
from app.iseol.graph import AgentGraphCompiler
from app.planning.models import PlanningHandoff


Runner = Callable[[list[str], str, float], str]


class IseolPlanBridge:
    """Call the local ISEOL planner through a versioned JSON stdin/stdout boundary."""

    def __init__(
        self,
        *,
        command: list[str] | None = None,
        timeout: float = 30.0,
        runner: Runner | None = None,
    ) -> None:
        if getattr(sys, "frozen", False):
            bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
            default_cli = bundle_root / "chatgpt-runtime" / "agent-organization" / "plan-cli.js"
        else:
            repo_root = Path(__file__).resolve().parents[4]
            default_cli = repo_root / "packages" / "iseol" / "dist" / "agent-organization" / "plan-cli.js"
        self.command = list(command or ["node", str(default_cli)])
        self.timeout = timeout
        self.runner = runner or self._run

    def create_plan(
        self,
        *,
        project_id: str,
        project_revision: str,
        request_id: str,
        request: RequestBrief,
        memory_ids: list[str],
        qa_baseline_ids: list[str],
        memory_context: list[dict[str, Any]] | None = None,
        planning_handoff: PlanningHandoff | None = None,
        intent: ProjectIntent | None = None,
        extensions: ExtensionRegistry | None = None,
    ) -> dict[str, Any]:
        intent = intent or _intent_from_request(request)
        if extensions is None:
            extensions = ExtensionRegistry()
            if intent.template_id == "meal_planner":
                extensions.register(ExtensionManifest(
                    id="meal-planner",
                    version="1.0.0",
                    kind="domain",
                    capabilities=["project.template.meal-planner"],
                ))
        graph = AgentGraphCompiler.compile(intent, extensions)
        graph = graph.model_copy(update={
            "context": {
                **graph.context,
                "verifiedMemories": list(memory_context or []),
            }
        })
        brief = ProjectBriefV1(
            schema_version=1,
            project_id=project_id,
            request_id=request_id,
            user_goal=request.goal,
            scope=[request.target_type, *request.acceptance_criteria],
            constraints=list(request.constraints),
            preferences={
                "canonicalIntent": request.canonical_intent,
                "verifiedMemories": list(memory_context or []),
            },
            schedule={},
            retrieved_memory_ids=list(memory_ids),
            qa_baseline_ids=list(qa_baseline_ids),
            created_at="2026-10-07T00:00:00+00:00",
        )
        payload = {
            "brief": brief.model_dump(mode="json", by_alias=True),
            "projectRevision": project_revision,
            "qualityMemory": list(memory_context or [
                {"id": item, "kind": "qa_rule", "status": "active", "content": item, "scope": {}}
                for item in memory_ids
            ]),
        }
        if planning_handoff is not None:
            if planning_handoff.project_id != project_id or planning_handoff.project_revision != project_revision:
                raise ValueError("planning handoff identity does not match ISEOL plan")
            payload["planningHandoff"] = planning_handoff.model_dump(mode="json", by_alias=True)
        native_fallback = False
        try:
            raw = self.runner(self.command, json.dumps(payload, ensure_ascii=False), self.timeout)
            value = json.loads(raw)
        except (OSError, subprocess.SubprocessError) as exc:
            # The native Python compiler is authoritative.  The Node planner
            # remains a compatibility input and must not block local execution.
            native_fallback = True
            value = {
                "schemaVersion": 1,
                "projectId": project_id,
                "requestId": request_id,
                "projectRevision": project_revision,
                "status": "planned",
                "tasks": [
                    {
                        "id": node.task_id,
                        "agentId": node.id,
                        "objective": node.goal,
                        "phase": node.phase,
                        "dependencies": list(node.dependencies),
                        "status": "planned",
                    }
                    for node in graph.agents
                ],
            }
        except json.JSONDecodeError as exc:
            raise RuntimeError("invalid ISEOL plan JSON") from exc
        if not isinstance(value, dict) or value.get("schemaVersion") != 1 or value.get("projectId") != project_id or not isinstance(value.get("tasks"), list):
            raise RuntimeError("invalid ISEOL plan")
        if planning_handoff is not None:
            value["planningHandoff"] = planning_handoff.model_dump(mode="json", by_alias=True)
        value["nativePlan"] = native_fallback
        value["intent"] = intent.model_dump(mode="json", by_alias=True)
        value["assumptions"] = list(intent.assumptions)
        value["selectedExtensions"] = list(graph.context.get("selectedExtensions", []))
        value["missingExtensions"] = list(graph.context.get("missingExtensions", []))
        value["agentGraph"] = graph.model_dump(
            mode="json", by_alias=True
        )
        return value

    @staticmethod
    def _run(command: list[str], payload: str, timeout: float) -> str:
        # Windows runners may use a legacy locale (for example ``cp1252``)
        # even though the project brief is UTF-8 Korean JSON.  Pin both
        # stdin and stdout decoding so natural-language requests cross the
        # ISEOL process boundary losslessly on every host.
        result = subprocess.run(
            command,
            input=payload,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, command, result.stdout, result.stderr)
        return result.stdout


def _intent_from_request(request: RequestBrief) -> ProjectIntent:
    template_id = "todo_app" if request.target_type == "todo_app" else (
        "generic_web" if request.target_type == "web_app" else None
    )
    return ProjectIntent(
        rawText=request.raw_text,
        goal=request.goal,
        projectType=request.target_type if request.target_type in {"web_app", "todo_app", "static_app"} else "unknown",
        templateId=template_id,
        constraints=list(request.constraints),
        acceptanceCriteria=list(request.acceptance_criteria),
    )
