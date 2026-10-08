from app.assistant.models import AssistantRequest
from app.assistant.registry import build_default_registry
from app.assistant.router import CapabilityRouter


def router() -> CapabilityRouter:
    return CapabilityRouter(build_default_registry())


def test_project_request_selects_project_execution() -> None:
    result = router().select(AssistantRequest(raw_text="웹 프로젝트 하나 만들어줘"))

    assert result.capability_id == "project-execution"
    assert result.status == "selected"
    assert result.reasons


def test_calendar_requests_select_the_matching_capability() -> None:
    calendar = router().select(AssistantRequest(raw_text="내일 오후 3시에 회의 일정 등록해줘"))

    assert calendar.capability_id == "personal-secretary"


def test_documents_and_presence_requests_select_the_matching_capability() -> None:
    documents = router().select(AssistantRequest(raw_text="이 문서 요약하고 기억해줘"))
    presence = router().select(AssistantRequest(raw_text="바탕화면 위젯으로 보여줘"))

    assert documents.capability_id == "knowledge-documents"
    assert presence.capability_id == "presence"


def test_ambiguous_request_requires_clarification() -> None:
    result = router().select(AssistantRequest(raw_text="이거 해줘"))

    assert result.status == "needs_clarification"
    assert result.capability_id is None
    assert result.candidates


def test_unmatched_conversation_uses_eeee_direct_capability() -> None:
    result = router().select(AssistantRequest(raw_text="안녕, 오늘 기분이 어때?"))

    assert result.status == "selected"
    assert result.capability_id == "general-conversation"
    assert result.reasons


def test_registered_explicit_capability_overrides_keyword_scoring() -> None:
    result = router().select(
        AssistantRequest(
            raw_text="프로젝트 관련 문서를 정리해줘",
            requested_capability="knowledge-documents",
        )
    )

    assert result.capability_id == "knowledge-documents"
    assert result.status == "selected"

