from app.memory.preferences import extract_preference


def test_extracts_explicit_language_preference():
    preference = extract_preference("앞으로 한국어로 답해줘")
    assert preference is not None
    assert (preference.key, preference.value) == ("language", "한국어")


def test_extracts_general_preference_without_guessing_when_not_explicit():
    assert extract_preference("오늘 한국어로 답해줘") is None


def test_keeps_unknown_explicit_preference_as_stable_note():
    first = extract_preference("기억해줘 포트폴리오 수준으로 완성해")
    second = extract_preference("기억해줘 포트폴리오 수준으로 완성해")
    assert first == second
from app.memory.preferences import extract_implicit_preference


def test_implicit_preference_extracts_durable_plugin_decision() -> None:
    result = extract_implicit_preference("포트폴리오는 나중에 플러그인으로 추가할거야")

    assert result is not None
    assert result.key == "architecture.portfolio_delivery"
    assert "선택 플러그인" in result.value


def test_implicit_preference_ignores_one_off_requests() -> None:
    assert extract_implicit_preference("Todo 앱 만들어줘") is None
