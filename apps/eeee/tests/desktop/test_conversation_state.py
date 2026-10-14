from app.desktop.conversation_state import ConversationPhase, ConversationState


def test_conversation_state_only_allows_idle_expiry_for_empty_input_or_finished_reply():
    state = ConversationState()

    state.open_input()
    assert state.phase is ConversationPhase.INPUT
    assert state.can_expire() is True

    state.update_draft("작성 중인 메시지")
    assert state.can_expire() is False

    state.begin_processing()
    assert state.phase is ConversationPhase.PROCESSING
    assert state.can_expire() is False

    state.begin_typing()
    assert state.phase is ConversationPhase.TYPING
    assert state.can_expire() is False

    state.finish_reply("답변")
    assert state.phase is ConversationPhase.REPLY
    assert state.can_expire() is True


def test_conversation_state_resets_to_empty_input_after_reply_click():
    state = ConversationState()
    state.finish_reply("이전 답변")

    state.open_input()

    assert state.phase is ConversationPhase.INPUT
    assert state.draft == ""
    assert state.message == ""
