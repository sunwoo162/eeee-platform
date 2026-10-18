import json
import threading

import httpx
import pytest

from app.agent.ollama_runtime import OllamaRuntime, OllamaRuntimeError


def test_ollama_runtime_streams_chat_deltas() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        content = "\n".join(
            [
                json.dumps({"message": {"content": "안"}, "done": False}, ensure_ascii=False),
                json.dumps({"message": {"content": "녕"}, "done": True}, ensure_ascii=False),
            ]
        ).encode("utf-8") + b"\n"
        return httpx.Response(200, content=content, request=request)

    runtime = OllamaRuntime(
        base_url="http://ollama.test",
        model="qwen2.5:7b",
        transport=httpx.MockTransport(handler),
    )

    chunks = list(runtime.stream([{"role": "user", "content": "안녕"}]))

    assert chunks == ["안", "녕"]
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/api/chat")
    assert seen["body"]["model"] == "qwen2.5:7b"
    assert seen["body"]["stream"] is True


def test_ollama_runtime_reports_missing_model_without_calling_provider() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500, request=request)

    runtime = OllamaRuntime(
        base_url="http://ollama.test",
        model=None,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(OllamaRuntimeError) as error:
        list(runtime.stream([]))

    assert error.value.code == "ollama_model_missing"
    assert called is False


def test_ollama_runtime_maps_malformed_stream_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json\n", request=request)

    runtime = OllamaRuntime(
        base_url="http://ollama.test",
        model="qwen2.5:7b",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(OllamaRuntimeError) as error:
        list(runtime.stream([]))

    assert error.value.code == "ollama_invalid_response"


def test_ollama_runtime_honors_cancellation_before_request() -> None:
    runtime = OllamaRuntime(
        base_url="http://ollama.test",
        model="qwen2.5:7b",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request)),
    )
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(OllamaRuntimeError) as error:
        list(runtime.stream([], cancel_event=cancelled))

    assert error.value.code == "ollama_cancelled"
