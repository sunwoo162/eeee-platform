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


def test_natural_language_question_with_request_suffix_stays_conversation() -> None:
    result = router().select(AssistantRequest(raw_text="내가 왜 피곤한지 설명해줘."))

    assert result.status == "selected"
    assert result.capability_id == "general-conversation"


def test_capability_question_about_development_stays_with_eeee() -> None:
    result = router().select(AssistantRequest(raw_text="너 개발 어느 정도 할 수 있어?"))

    assert result.capability_id == "general-conversation"
    assert result.status == "selected"
    assert "informational capability question" in result.reasons


def test_connected_plugin_capability_can_win_routing_but_unavailable_plugin_cannot() -> None:
    from app.assistant.models import CapabilityDescriptor
    from app.assistant.registry import CapabilityRegistry

    registry = CapabilityRegistry()
    registry.register(
        CapabilityDescriptor(
            id="general-conversation", version="1.0.0", display_name="EEEE",
            intents=["conversation"], trigger_phrases=["hello"], required_connectors=[],
            side_effect_level="none", approval_level="none", claim_latch_policy="claimlatch-v0.2.0",
        ),
        None,
    )
    enabled = False
    plugin_descriptor = CapabilityDescriptor(
        id="plugin:notion:search", version="1.0.0", display_name="Notion Search",
        intents=["search"], trigger_phrases=["notion search"], required_connectors=["plugin:notion"],
        side_effect_level="none", approval_level="none", claim_latch_policy="claimlatch-v0.2.0",
    )
    registry.set_dynamic_provider(lambda: [plugin_descriptor] if enabled else [])
    router = CapabilityRouter(registry)

    unavailable = router.select(AssistantRequest(raw_text="notion search"))
    assert unavailable.status == "plugin_required"
    assert unavailable.required_plugin_id == "notion"
    enabled = True
    assert router.select(AssistantRequest(raw_text="notion search")).capability_id == "plugin:notion:search"


def test_known_optional_plugin_request_is_not_misreported_as_general_conversation() -> None:
    result = router().select(AssistantRequest(raw_text="노션에 회의록 저장해줘"))

    assert result.status == "plugin_required"
    assert result.required_plugin_id == "notion"
    assert result.required_plugin_name == "Notion"


def test_known_first_party_plugin_request_suggests_installation() -> None:
    result = router().select(AssistantRequest(raw_text="Gmail에서 안 읽은 메일 찾아줘"))

    assert result.status == "plugin_required"
    assert result.required_plugin_id == "gmail"
    assert result.required_plugin_name == "Gmail"


def test_registered_explicit_capability_overrides_keyword_scoring() -> None:
    result = router().select(
        AssistantRequest(
            raw_text="프로젝트 관련 문서를 정리해줘",
            requested_capability="knowledge-documents",
        )
    )

    assert result.capability_id == "knowledge-documents"
    assert result.status == "selected"


def test_connected_mail_send_action_beats_broad_mail_read_trigger() -> None:
    from app.assistant.models import CapabilityDescriptor
    from app.assistant.registry import CapabilityRegistry

    registry = CapabilityRegistry()
    registry.set_dynamic_provider(lambda: [
        CapabilityDescriptor(
            id="plugin:gmail:mail.list", version="1.0.0", display_name="Gmail Mail",
            intents=["email"], trigger_phrases=["메일", "gmail"],
            required_connectors=["plugin:gmail"], side_effect_level="none",
            approval_level="none", claim_latch_policy="claimlatch-v0.2.0",
        ),
        CapabilityDescriptor(
            id="plugin:gmail:mail.send", version="1.0.0", display_name="Gmail Send",
            intents=["email"], trigger_phrases=["메일 보내", "gmail"],
            required_connectors=["plugin:gmail"], side_effect_level="external",
            approval_level="user", claim_latch_policy="claimlatch-v0.2.0",
        ),
    ])

    result = CapabilityRouter(registry).select(
        AssistantRequest(raw_text="s25011@gsm.hs.kr 에 test라는 메일 보내")
    )

    assert result.capability_id == "plugin:gmail:mail.send"

