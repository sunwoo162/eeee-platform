import pytest

from app.agent.provider_policy import ProviderPolicy


def test_simple_conversation_prefers_web_provider():
    decision = ProviderPolicy().choose("안녕 오늘 기분이 어때?", local_available=True, web_available=True)

    assert decision.provider == "web"
    assert decision.reason == "web_primary"


def test_project_work_prefers_web_provider():
    decision = ProviderPolicy().choose("Todo 앱 만들어줘", local_available=True, web_available=True)

    assert decision.provider == "web"
    assert decision.reason == "complex_or_tool_request"


def test_simple_conversation_uses_web_when_local_is_unavailable():
    decision = ProviderPolicy().choose("안녕", local_available=False, web_available=True)

    assert decision.provider == "web"
    assert decision.reason == "web_primary"


def test_unavailable_providers_are_reported_truthfully():
    decision = ProviderPolicy().choose("안녕", local_available=False, web_available=False)

    assert decision.provider == "unavailable"
    assert decision.reason == "no_provider_available"


@pytest.mark.parametrize(
    "prompt",
    [
        "안녕",
        "안녕, 오늘 기분이 어때?",
        "고마워요",
        "지금 뭐해",
        "너는 어느 정도까지 할 수 있어?",
        "ㅇㅇ 알겠어",
        "오늘 기분이 조금 가라앉았어",
        "이야기하고 싶어",
    ],
)
def test_builtin_eligibility_allows_only_bounded_basic_intents(prompt):
    assert ProviderPolicy.is_builtin_eligible(prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        "오늘 기분이 어때? 날씨 알려줘",
        "오늘 날씨 어때?",
        "대한민국의 수도는 어디야?",
        "코드 작성해줘",
        "안녕 그리고 코드 작성해줘",
    ],
)
def test_builtin_eligibility_rejects_mixed_fact_and_task_requests(prompt):
    assert not ProviderPolicy.is_builtin_eligible(prompt)


def test_builtin_fallback_does_not_select_for_a_mixed_request():
    decision = ProviderPolicy().choose(
        "오늘 기분이 어때? 날씨 알려줘",
        local_available=False,
        web_available=False,
        builtin_available=True,
    )

    assert decision.provider == "unavailable"
    assert decision.reason == "no_provider_available"
