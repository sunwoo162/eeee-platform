from app.desktop.session import ConversationSession
from app.desktop.worker import ConversationWorker


class FakeClient:
    def __init__(self):
        self.events = [
            {"eventType": "message.completed", "payload": {"content": "완료"}}
        ]

    def stream_request_events(self, request_id):
        assert request_id == "request-1"
        return iter(self.events)


class NetworkClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    def create_conversation(self):
        self.calls.append("create")
        return {"id": "conversation-1"}

    def submit_turn(self, conversation_id, content, client_message_id):
        self.calls.append(("submit", conversation_id, content, client_message_id))
        return {"requestId": "request-1"}


class FakeSession:
    def __init__(self):
        self.state = "streaming"
        self.messages = [{"role": "assistant", "content": "완료"}]

    def submit(self, text):
        assert text == "실행"
        return {"requestId": "request-1"}

    def apply_events(self, request, events):
        assert request["requestId"] == "request-1"
        assert events
        self.state = "answer"


def test_conversation_worker_keeps_network_work_outside_the_widget():
    session = FakeSession()
    result = ConversationWorker(FakeClient(), session).run_turn("실행")

    assert result["state"] == "answer"
    assert result["events"][0]["eventType"] == "message.completed"


def test_conversation_worker_does_not_mutate_production_session():
    client = NetworkClient()
    session = ConversationSession(client)
    session.prepare_turn("실행")
    submission = {
        "conversationId": session.conversation_id,
        "clientMessageId": "desktop-test-1",
        "content": "실행",
    }

    result = ConversationWorker(client, session).run_turn(
        submission["content"],
        conversation_id=submission["conversationId"],
        client_message_id=submission["clientMessageId"],
    )

    assert result["request"]["requestId"] == "request-1"
    assert client.calls == [
        "create",
        ("submit", "conversation-1", "실행", "desktop-test-1"),
    ]
    assert session.messages == []
    assert session.state == "submitting"
