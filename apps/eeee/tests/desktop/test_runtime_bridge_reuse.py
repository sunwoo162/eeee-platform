from app.desktop.runtime import (
    _chatgpt_bridge_is_healthy,
    _chatgpt_bridge_is_stale,
    _terminate_port_owner,
)


def test_chatgpt_bridge_health_requires_connected_response(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b'{"status":"ok","service":"chatgpt-web-bridge","connected":true,"browserStatus":"ready"}'

    monkeypatch.setattr("app.desktop.runtime.urllib.request.urlopen", lambda *_args, **_kwargs: Response())

    assert _chatgpt_bridge_is_healthy(47831) is True


def test_chatgpt_bridge_health_rejects_disconnected_response(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b'{"status":"ok","service":"chatgpt-web-bridge","connected":false}'

    monkeypatch.setattr("app.desktop.runtime.urllib.request.urlopen", lambda *_args, **_kwargs: Response())

    assert _chatgpt_bridge_is_healthy(47831) is False


def test_chatgpt_bridge_health_fails_closed(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("app.desktop.runtime.urllib.request.urlopen", unavailable)

    assert _chatgpt_bridge_is_healthy(47831) is False


def test_chatgpt_bridge_health_rejects_legacy_transport_only_response(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b'{"status":"ok","service":"chatgpt-web-bridge","connected":true}'

    monkeypatch.setattr("app.desktop.runtime.urllib.request.urlopen", lambda *_args, **_kwargs: Response())

    assert _chatgpt_bridge_is_healthy(47831) is False
    assert _chatgpt_bridge_is_stale(47831) is True


def test_chatgpt_bridge_stale_health_is_detected(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b'{"status":"ok","service":"chatgpt-web-bridge","connected":false}'

    monkeypatch.setattr("app.desktop.runtime.urllib.request.urlopen", lambda *_args, **_kwargs: Response())

    assert _chatgpt_bridge_is_stale(47831) is True


def test_port_owner_termination_uses_windows_process_tree(monkeypatch):
    calls = []

    class Result:
        stdout = "  TCP    127.0.0.1:47831    0.0.0.0:0    LISTENING    1234\n"

    monkeypatch.setattr("app.desktop.runtime.os.name", "nt")
    monkeypatch.setattr("app.desktop.runtime.subprocess.run", lambda args, **kwargs: (calls.append(args) or Result()))

    assert _terminate_port_owner(47831) is True
    assert calls == [
        ["netstat", "-ano", "-p", "tcp"],
        ["taskkill", "/PID", "1234", "/T", "/F"],
    ]
