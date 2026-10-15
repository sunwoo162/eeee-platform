from app.desktop.worker import ConversationWorker


class FakeClient:
    def __init__(self):
        self.events = [
            {"eventType": "message.completed", "payload": {"content": "완료"}}
        ]

    def stream_request_events(self, request_id):
        assert request_id == "request-1"
        return iter(self.events)


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
