from app.desktop.session import ConversationSession


class FakeConversationClient:
    def __init__(self):
        self.created = []
        self.submitted = []

    def create_conversation(self, title="새 대화"):
        self.created.append(title)
        return {"id": "conversation-1", "title": title}

    def submit_turn(self, conversation_id, content, client_message_id):
        self.submitted.append((conversation_id, content, client_message_id))
        return {"requestId": "request-1", "state": "persisted_user_message"}


def test_session_persists_turn_and_replaces_streaming_answer_without_losing_user_text():
    client = FakeConversationClient()
    session = ConversationSession(client)

    request = session.submit("오늘 뭐해?")
    session.apply_events(
        request,
        [
            {"eventType": "message.started", "payload": {"messageId": "message-1"}},
            {"eventType": "message.delta", "payload": {"messageId": "message-1", "delta": "안녕"}},
            {"eventType": "message.delta", "payload": {"messageId": "message-1", "delta": "!"}},
            {"eventType": "message.completed", "payload": {"messageId": "message-1", "content": "안녕!"}},
        ],
    )

    assert request["requestId"] == "request-1"
    assert session.state == "answer"
    assert [message["content"] for message in session.messages] == ["오늘 뭐해?", "안녕!"]

    session.begin_input()
    assert session.state == "input"
    assert session.draft == ""


def test_session_preserves_draft_when_core_submission_fails():
    class BrokenClient(FakeConversationClient):
        def create_conversation(self, title="새 대화"):
            raise RuntimeError("Core offline")

    session = ConversationSession(BrokenClient())

    try:
        session.submit("보존해야 해")
    except RuntimeError:
        pass

    assert session.state == "error"
    assert session.draft == "보존해야 해"


def test_session_reconnects_by_reloading_persisted_transcript():
    class HistoryClient(FakeConversationClient):
        def get_conversation_messages(self, conversation_id):
            assert conversation_id == "conversation-1"
            return {"items": [{"role": "user", "content": "기록"}]}

    session = ConversationSession(HistoryClient())
    session.open("conversation-1")

    assert session.reconnect() == [{"role": "user", "content": "기록"}]
    assert session.state == "idle"


def test_session_commits_worker_result_only_when_the_qt_callback_runs():
    session = ConversationSession(FakeConversationClient())

    submission = session.prepare_turn("콜백에서 반영")
    assert session.state == "submitting"
    assert session.messages == []

    session.commit_turn(
        submission,
        {"requestId": "request-1"},
        [{"eventType": "message.completed", "payload": {"content": "완료"}}],
        conversation_id="conversation-1",
    )

    assert session.conversation_id == "conversation-1"
    assert session.state == "answer"
    assert [message["content"] for message in session.messages] == ["콜백에서 반영", "완료"]


def test_session_marks_worker_failure_without_discarding_the_draft():
    session = ConversationSession(FakeConversationClient())
    session.prepare_turn("복원해야 해")

    session.mark_error()

    assert session.state == "error"
    assert session.draft == "복원해야 해"
