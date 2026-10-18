from app.plugins.intents import build_plugin_action_input


def test_gmail_read_intent_extracts_unread_filter_and_limit() -> None:
    assert build_plugin_action_input(
        "gmail", "mail.list", "새 메일 목록 5개 보여줘"
    ) == {"limit": 5}
    assert build_plugin_action_input(
        "gmail", "mail.list", "안 읽은 메일 찾아줘"
    ) == {"limit": 10, "query": "is:unread"}


def test_gmail_send_intent_extracts_recipient_subject_and_body() -> None:
    assert build_plugin_action_input(
        "gmail", "mail.send", "s25011@gsm.hs.kr 에 test라는 메일 보내"
    ) == {
        "to": "s25011@gsm.hs.kr",
        "subject": "test",
        "body": "test",
    }


def test_gmail_send_intent_rejects_missing_recipient() -> None:
    try:
        build_plugin_action_input("gmail", "mail.send", "test라는 메일 보내")
    except ValueError as exc:
        assert "받는 사람" in str(exc)
    else:
        raise AssertionError("missing recipient must not be executable")
