import json
import threading

import httpx
import pytest

from app.agent.personal_llm_runtime import (
    PersonalLlmRuntime,
    PersonalLlmRuntimeError,
)


def _chat_response(*, request_id: str = "request-1", text: str = "답변", **extra: object) -> dict:
    payload = {
        "requestId": request_id,
        "modelVersion": "qwen2.5-0.5b-instruct+lora",
        "profileRevision": 0,
        "text": text,
        "intent": "assistant_reply",
        "styleApplied": True,
        "memoryUsed": [],
        "confidence": 0.8,
        "actionProposal": None,
        "needsUserConfirmation": False,
        "status": "completed",
    }
    payload.update(extra)
    return payload


def test_status_discovers_ready_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/model/status"
        return httpx.Response(
            200,
            json={"configured": True, "modelVersion": "qwen2.5-0.5b-instruct+lora"},
            request=request,
        )

    runtime = PersonalLlmRuntime(
        base_url="http://personal.test",
        transport=httpx.MockTransport(handler),
    )

    status = runtime.status()

    assert status.status == "ready"
    assert status.model == "qwen2.5-0.5b-instruct+lora"
    assert status.error_code is None


def test_chat_posts_exact_scoped_contract_and_returns_text() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["header"] = request.headers["X-Personal-User-Id"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_chat_response(), request=request)

    runtime = PersonalLlmRuntime(
        base_url="http://personal.test/",
        transport=httpx.MockTransport(handler),
    )

    answer = runtime.chat(
        [
            {"role": "system", "content": "너는 EEEE야."},
            {"role": "user", "content": "안녕"},
        ],
        user_id="user-a",
        request_id="request-1",
        conversation_id="conversation-1",
    )

    assert answer == "답변"
    assert seen["method"] == "POST"
    assert seen["url"] == "http://personal.test/v1/chat"
    assert seen["header"] == "user-a"
    assert seen["body"] == {
        "requestId": "request-1",
        "userId": "user-a",
        "mode": "assistant",
        "profileRevision": 0,
        "conversationId": "conversation-1",
        "messages": [
            {"role": "system", "content": "너는 EEEE야."},
            {"role": "user", "content": "안녕"},
        ],
        "approvedMemoryIds": [],
    }


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(503, json={"error": {"code": "backend_error"}}), "personal_llm_http_error"),
        (httpx.Response(200, content=b"not-json"), "personal_llm_invalid_response"),
        (httpx.Response(200, json=_chat_response(text="   ")), "personal_llm_empty_response"),
    ],
)
def test_chat_maps_http_malformed_and_empty_responses(
    response: httpx.Response, code: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response.request = request
        return response

    runtime = PersonalLlmRuntime(
        base_url="http://personal.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PersonalLlmRuntimeError) as error:
        runtime.chat([], user_id="user-a", request_id="request-1", conversation_id="conversation-1")

    assert error.value.code == code


def test_chat_rejects_a_response_for_another_user() -> None:
    runtime = PersonalLlmRuntime(
        base_url="http://personal.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=_chat_response(userId="user-b"),
                request=request,
            )
        ),
    )

    with pytest.raises(PersonalLlmRuntimeError) as error:
        runtime.chat([], user_id="user-a", request_id="request-1", conversation_id="conversation-1")

    assert error.value.code == "personal_llm_user_scope_mismatch"


def test_chat_maps_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("generation timed out", request=request)

    runtime = PersonalLlmRuntime(
        base_url="http://personal.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PersonalLlmRuntimeError) as error:
        runtime.chat([], user_id="user-a", request_id="request-1", conversation_id="conversation-1")

    assert error.value.code == "personal_llm_timeout"


def test_chat_honors_cancellation_before_and_after_request() -> None:
    cancelled = threading.Event()
    cancelled.set()
    runtime = PersonalLlmRuntime(
        base_url="http://personal.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=_chat_response(), request=request)),
    )

    with pytest.raises(PersonalLlmRuntimeError) as error:
        runtime.chat(
            [],
            user_id="user-a",
            request_id="request-1",
            conversation_id="conversation-1",
            cancel_event=cancelled,
        )
    assert error.value.code == "conversation_cancelled"

    cancelled.clear()

    def late_handler(request: httpx.Request) -> httpx.Response:
        cancelled.set()
        return httpx.Response(200, json=_chat_response(), request=request)

    runtime = PersonalLlmRuntime(
        base_url="http://personal.test",
        transport=httpx.MockTransport(late_handler),
    )
    with pytest.raises(PersonalLlmRuntimeError) as error:
        runtime.chat(
            [],
            user_id="user-a",
            request_id="request-1",
            conversation_id="conversation-1",
            cancel_event=cancelled,
        )
    assert error.value.code == "conversation_cancelled"
