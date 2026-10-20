import json
from pathlib import Path

import httpx

from plugins.eeee_chat_history.main import CoreApiClient
from app.plugins.manifest import discover_manifest

PACKAGE = Path(__file__).parents[2] / "plugins" / "eeee_chat_history"
PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"


def test_bundled_chat_history_package_has_a_strict_manifest_and_entrypoint() -> None:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["id"] == "eeee-chat-history"
    assert manifest["command"][-1] == "main.py"
    assert manifest["memoryScope"] == "conversation"
    assert discover_manifest(manifest).id == "eeee-chat-history"
    assert (PACKAGE / "main.py").is_file()
    assert (PACKAGE / "window.py").is_file()


def test_chat_history_client_reads_the_canonical_conversation_store(monkeypatch) -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []

    def request(method: str, url: str, **kwargs):
        requests.append((method, url, kwargs))
        if url.endswith("/v1/conversations"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "conversation-1",
                            "title": "오늘 식단",
                            "updatedAt": "2026-10-19T00:00:00+00:00",
                        }
                    ],
                    "nextCursor": None,
                },
            )
        if url.endswith("/v1/conversations/conversation-1/messages"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "message-1",
                            "role": "user",
                            "content": "오늘 식단 정리해줘",
                            "status": "completed",
                            "sequence": 1,
                        },
                        {
                            "id": "message-2",
                            "role": "assistant",
                            "content": "정리했어.",
                            "status": "completed",
                            "sequence": 2,
                        },
                    ],
                    "nextCursor": None,
                },
            )
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(httpx, "request", request)
    client = CoreApiClient("http://127.0.0.1:8123")

    assert client.get_conversations() == [
        {
            "conversationId": "conversation-1",
            "preview": "오늘 식단",
            "messageCount": 0,
            "updatedAt": "2026-10-19T00:00:00+00:00",
        }
    ]
    assert client.get_conversation("conversation-1")["turns"][1]["content"] == "정리했어."
    assert [item[1] for item in requests] == [
        "http://127.0.0.1:8123/v1/conversations",
        "http://127.0.0.1:8123/v1/conversations/conversation-1/messages",
    ]


def test_chat_history_client_uses_the_canonical_message_cursor(monkeypatch) -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []

    def request(method: str, url: str, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "message-3",
                        "role": "user",
                        "content": "세 번째",
                        "status": "completed",
                        "sequence": 3,
                    }
                ],
                "nextCursor": 3,
            },
        )

    monkeypatch.setattr(httpx, "request", request)
    client = CoreApiClient("http://127.0.0.1:8123")

    page = client.get_conversation("conversation-1", after_sequence=2, limit=1)

    assert page["nextAfterSequence"] == 3
    assert page["turns"][0]["content"] == "세 번째"
    assert requests[0][2]["params"] == {"afterSequence": 2, "limit": 1}


def test_chat_history_client_sends_an_idempotent_canonical_turn(monkeypatch) -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []

    def request(method: str, url: str, **kwargs):
        requests.append((method, url, kwargs))
        if url.endswith("/v1/conversations/conversation-1/turns"):
            return httpx.Response(202, json={"requestId": "request-1", "state": "received"})
        raise AssertionError(f"unexpected request: {method} {url}")

    class EventStream:
        is_error = False
        text = ""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_lines(self):
            return [
                'data: {"eventType":"message.completed","payload":{"content":"완료했어."}}',
                "",
            ]

    monkeypatch.setattr(httpx, "request", request)
    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: EventStream())

    result = CoreApiClient("http://127.0.0.1:8123").send_conversation_message(
        "다음 작업", conversation_id="conversation-1"
    )

    assert result == {
        "status": "completed",
        "message": "완료했어.",
        "requestId": "request-1",
        "conversationId": "conversation-1",
    }
    assert requests[0][1].endswith("/v1/conversations/conversation-1/turns")
    payload = requests[0][2]["json"]
    assert payload["content"] == "다음 작업"
    assert str(payload["clientMessageId"]).startswith("eeee-chat-history-")


def test_chat_history_package_is_included_in_python_distribution() -> None:
    pyproject = PYPROJECT.read_text(encoding="utf-8")

    assert 'include = ["app*", "plugins*"]' in pyproject
    assert 'plugins = ["*.json"]' in pyproject
