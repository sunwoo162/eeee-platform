from app.desktop.plugin_presentation import format_plugin_output


def test_gmail_message_results_are_summarized_for_the_pet_bubble():
    result = format_plugin_output(
        {
            "action": "mail.list",
            "output": {
                "messages": [
                    {
                        "subject": "회의 일정",
                        "from": "alice@example.com",
                        "date": "Wed, 15 Oct 2026 09:00:00 +0900",
                        "snippet": "내일 회의 시간 확인 부탁드립니다.",
                        "isUnread": True,
                    }
                ]
            },
        }
    )

    assert result == "메일 1개를 찾았어.\n1. [안 읽음] 회의 일정 · alice@example.com\n내일 회의 시간 확인 부탁드립니다."


def test_gmail_send_result_is_summarized_without_leaking_provider_payload():
    result = format_plugin_output(
        {
            "action": "mail.send",
            "output": {"sent": True, "id": "provider-message-id"},
        }
    )

    assert result == "메일을 보냈어."
    assert "provider-message-id" not in result


def test_empty_plugin_output_does_not_add_an_empty_bubble_section():
    assert format_plugin_output({"action": "mail.list", "output": {"messages": []}}) == "메일을 찾지 못했어."
