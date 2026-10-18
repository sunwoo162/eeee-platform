from app.assistant.models import AssistantContext, AssistantRequest
from app.contracts import ExecutionStatus
from app.iseol.orchestrator import IseolOrchestrator


def test_orchestrator_runs_one_sentence_web_request_to_verified_local_result() -> None:
    calls: list[str] = []

    def runner(request, _context, _envelope):
        calls.append(request.raw_text)
        return {"status": "completed", "projectId": "project-1", "qualityStatus": "PASS"}

    result = IseolOrchestrator(runner=runner).run(
        AssistantRequest(raw_text="오늘 식단 정리해주는 웹 만들어줘"),
        AssistantContext(),
        object(),
    )

    assert result["status"] == "completed"
    assert result["qualityStatus"] == "PASS"
    assert calls == ["오늘 식단 정리해주는 웹 만들어줘"]


def test_orchestrator_resume_preserves_project_identity_and_is_idempotent_at_boundary() -> None:
    seen: list[str | None] = []

    def runner(request, _context, _envelope):
        seen.append(request.context.get("resumeProjectId"))
        return {"status": "completed", "projectId": request.context.get("resumeProjectId", "project-new")}

    orchestrator = IseolOrchestrator(runner=runner)
    request = AssistantRequest(raw_text="메모 웹 만들어줘")
    first = orchestrator.run(request, AssistantContext(), object())
    resumed = orchestrator.resume("project-1", request, AssistantContext(), object())

    assert first["projectId"] == "project-new"
    assert resumed["projectId"] == "project-1"
    assert seen == [None, "project-1"]


def test_orchestrator_blocks_external_action_without_approval() -> None:
    called = False

    def runner(*_args):
        nonlocal called
        called = True
        return {"status": "completed"}

    result = IseolOrchestrator(runner=runner).run(
        AssistantRequest(
            raw_text="웹을 배포해줘",
            context={"externalActionRequired": True, "approved": False},
        ),
        AssistantContext(),
        object(),
    )

    assert result.status is ExecutionStatus.BLOCKED
    assert result.output["status"] == "blocked"
    assert called is False
