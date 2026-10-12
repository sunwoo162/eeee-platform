import httpx

from app.agent.local_model_discovery import discover_local_model


def test_discover_local_model_selects_first_installed_ollama_model(monkeypatch):
    def request(method, url, **kwargs):
        assert method == "GET"
        assert url == "http://127.0.0.1:11434/api/tags"
        return httpx.Response(
            200,
            json={"models": [{"name": "qwen2.5:3b"}, {"name": "llama3.2:3b"}]},
        )

    monkeypatch.setattr(httpx, "request", request)

    assert discover_local_model("http://127.0.0.1:11434/api/chat") == "qwen2.5:3b"


def test_discover_local_model_prefers_newer_general_chat_model(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *args, **kwargs: httpx.Response(
            200,
            json={"models": [{"name": "qwen2.5:1.5b"}, {"name": "qwen3:4b"}]},
        ),
    )

    assert discover_local_model("http://127.0.0.1:11434/api/chat") == "qwen3:4b"


def test_discover_local_model_returns_none_when_ollama_is_unavailable(monkeypatch):
    def request(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "request", request)

    assert discover_local_model("http://127.0.0.1:11434/api/chat") is None


def test_discover_local_model_ignores_malformed_model_entries(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *args, **kwargs: httpx.Response(200, json={"models": [{"digest": "x"}, "bad"]}),
    )

    assert discover_local_model("http://127.0.0.1:11434/api/chat") is None
