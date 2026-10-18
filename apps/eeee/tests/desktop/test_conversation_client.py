import httpx

from app.desktop.client import PetApiClient


def test_desktop_client_uses_v1_conversation_contract(monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        if url.endswith("/v1/conversations") and method == "POST":
            return httpx.Response(201, json={"id": "conversation-1", "title": "새 대화"})
        return httpx.Response(202, json={"requestId": "request-1", "state": "persisted_user_message"})

    monkeypatch.setattr(httpx, "request", request)
    client = PetApiClient("http://127.0.0.1:8123")

    assert client.create_conversation()["id"] == "conversation-1"
    assert client.submit_turn("conversation-1", "안녕", "client-1")["requestId"] == "request-1"
    assert requests == [
        (
            "POST",
            "http://127.0.0.1:8123/v1/conversations",
            {"timeout": 5.0, "json": {"title": "새 대화"}},
        ),
        (
            "POST",
            "http://127.0.0.1:8123/v1/conversations/conversation-1/turns",
            {
                "timeout": 5.0,
                "json": {"clientMessageId": "client-1", "content": "안녕"},
            },
        ),
    ]


def test_desktop_client_parses_replayed_sse_events(monkeypatch):
    class StreamResponse:
        is_error = False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield 'data: {"eventType":"message.delta","payload":{"delta":"안녕"}}'
            yield ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: StreamResponse())

    events = list(PetApiClient("http://127.0.0.1:8123").stream_request_events("request-1"))

    assert events == [
        {"eventType": "message.delta", "payload": {"delta": "안녕"}}
    ]
