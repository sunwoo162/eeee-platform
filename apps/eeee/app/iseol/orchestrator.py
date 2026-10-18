"""Native orchestration boundary for project execution and safe resume."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.assistant.models import AssistantContext, AssistantRequest
from app.contracts import ExecutionEnvelope, ExecutionStatus, ExecutionError


Runner = Callable[[AssistantRequest, AssistantContext, Any], Any]


class IseolOrchestrator:
    """Keep project execution behind one resumable, approval-aware boundary.

    The kernel still owns the durable execution envelope. This class owns the
    project-run contract so a future desktop, API, or plugin entry point can
    reuse the same local execution path without copying the workflow.
    """

    def __init__(self, *, runner: Runner) -> None:
        self._runner = runner

    def run(
        self,
        request: AssistantRequest,
        context: AssistantContext,
        envelope: ExecutionEnvelope | Any,
    ) -> Any:
        blocked = self._external_approval_block(request)
        if blocked is not None:
            return blocked
        return self._runner(request, context, envelope)

    def resume(
        self,
        project_id: str,
        request: AssistantRequest,
        context: AssistantContext,
        envelope: ExecutionEnvelope | Any,
    ) -> Any:
        if not project_id.strip():
            raise ValueError("project_id is required for resume")
        resumed = request.model_copy(update={
            "context": {**request.context, "resumeProjectId": project_id},
        })
        return self.run(resumed, context, envelope)

    @staticmethod
    def _external_approval_block(request: AssistantRequest) -> Any | None:
        if request.context.get("externalActionRequired") and request.context.get("approved") is not True:
            # Import lazily: the kernel adapter defines CapabilityOutcome and
            # imports this module, so importing it at module load would cycle.
            from app.kernel.capabilities import CapabilityOutcome

            error = ExecutionError(
                code="external_approval_required",
                message="External action requires explicit user approval",
            )
            return CapabilityOutcome(
                {
                    "status": "blocked",
                    "message": "외부 작업은 사용자 승인이 있어야 실행할 수 있어.",
                    "approvalRequired": True,
                },
                ExecutionStatus.BLOCKED,
                error,
            )
        return None
