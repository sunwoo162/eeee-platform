from app.agent.provider_policy import ProviderPolicy


def test_simple_conversation_prefers_local_provider():
    decision = ProviderPolicy().choose("안녕 오늘 기분이 어때?", local_available=True, web_available=True)

    assert decision.provider == "local"
    assert decision.reason == "simple_request"


def test_project_work_prefers_web_provider():
    decision = ProviderPolicy().choose("Todo 앱 만들어줘", local_available=True, web_available=True)

    assert decision.provider == "web"
    assert decision.reason == "complex_or_tool_request"


def test_connected_web_provider_handles_simple_request_when_local_is_unavailable():
    decision = ProviderPolicy().choose("안녕", local_available=False, web_available=True)

    assert decision.provider == "web"
    assert decision.reason == "local_unavailable"


def test_unavailable_providers_are_reported_truthfully():
    decision = ProviderPolicy().choose("안녕", local_available=False, web_available=False)

    assert decision.provider == "unavailable"
    assert decision.reason == "no_provider_available"
