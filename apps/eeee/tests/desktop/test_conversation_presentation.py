from app.desktop.presentation import BubbleLayout, ConversationPresentation


def test_conversation_presentation_has_explicit_lifecycle_states():
    assert ConversationPresentation.for_input().state == "input"
    assert ConversationPresentation.for_submission("입력").state == "submitting"
    assert ConversationPresentation.for_stream("답변").state == "streaming"
    assert ConversationPresentation.for_answer("답변").state == "answer"
    assert ConversationPresentation.for_error("오류").state == "error"


def test_bubble_layout_grows_with_text_lines_without_fixed_height():
    layout = BubbleLayout(max_width=420)

    one_line = layout.measure("짧은 답변")
    three_lines = layout.measure("첫째 줄\n둘째 줄\n셋째 줄")
    ten_lines = layout.measure("\n".join(f"{index}번째 줄" for index in range(10)))

    assert one_line.height < three_lines.height < ten_lines.height
    assert one_line.height != 24
    assert ten_lines.height > 200
