from email import policy
from email.parser import BytesParser

from app.plugins.providers import build_gmail_connector


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class QueueTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers, params=None, json=None):
        self.calls.append({
            "method": method,
            "url": url,
            "headers": headers,
            "params": params,
            "json": json,
        })
        return self.responses.pop(0)


def test_gmail_mail_list_fetches_and_normalizes_message_metadata() -> None:
    transport = QueueTransport(
        FakeResponse(200, {"messages": [{"id": "m1", "threadId": "t1"}], "nextPageToken": "next"}),
        FakeResponse(200, {
            "id": "m1",
            "threadId": "t1",
            "snippet": "회의 안내",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {"headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "Subject", "value": "회의 안내"},
                {"name": "Date", "value": "Wed, 15 Oct 2026 09:00:00 +0900"},
            ]},
        }),
    )
    connector = build_gmail_connector("https://gmail.example", transport)
    connection = connector.connect("user-a", {"access_token": "secret"}, {"mail.read"})

    result = connector.invoke(connection, "mail.list", {"limit": 1, "query": "is:unread"})

    assert result == {
        "messages": [{
            "id": "m1",
            "threadId": "t1",
            "from": "sender@example.com",
            "subject": "회의 안내",
            "date": "Wed, 15 Oct 2026 09:00:00 +0900",
            "snippet": "회의 안내",
            "isUnread": True,
        }],
        "nextPageToken": "next",
    }
    assert transport.calls[0]["method"] == "GET"
    assert transport.calls[0]["params"] == {"maxResults": 1, "q": "is:unread"}
    assert transport.calls[0]["json"] is None
    assert transport.calls[1]["url"].endswith("/users/me/messages/m1")
    assert transport.calls[1]["params"] == {
        "format": "metadata",
        "metadataHeaders": ["From", "Subject", "Date"],
    }


def test_gmail_mail_send_builds_rfc822_payload_from_structured_fields() -> None:
    transport = QueueTransport(FakeResponse(200, {"id": "sent-1", "threadId": "thread-1"}))
    connector = build_gmail_connector("https://gmail.example", transport)
    connection = connector.connect("user-a", {"access_token": "secret"}, {"mail.send"})

    result = connector.invoke(connection, "mail.send", {
        "to": "s25011@gsm.hs.kr",
        "subject": "test",
        "body": "본문 테스트",
    })

    assert result == {"sent": True, "id": "sent-1", "threadId": "thread-1"}
    request = transport.calls[0]
    assert request["method"] == "POST"
    assert request["url"].endswith("/users/me/messages/send")
    assert set(request["json"]) == {"raw"}
    message = BytesParser(policy=policy.default).parsebytes(
        __import__("base64").urlsafe_b64decode(request["json"]["raw"] + "===")
    )
    assert message["To"] == "s25011@gsm.hs.kr"
    assert message["Subject"] == "test"
    assert message.get_content().strip() == "본문 테스트"
