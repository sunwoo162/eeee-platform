"""Fake Codex app-server: handshake, text deltas, file approvals and cancel."""
import json
import queue
import time

from app.codex_integration.runtime import CodexTaskManager


class FakePipe:
    def __init__(self):
        self.messages = queue.Queue()
        self.received = []
        self.exit_code = None
        self.stdout = self
        self.stdin = self
        self.writes = []
        self.request_approval = False

    def __iter__(self):
        while True:
            item = self.messages.get(timeout=3)
            if item is None:
                return
            yield json.dumps(item) + "\n"

    def write(self, line):
        packet = json.loads(line)
        self.writes.append(packet)
        if packet.get("method") == "initialize":
            self.messages.put({"id": packet["id"], "result": {"platformFamily": "windows"}})
        elif packet.get("method") == "thread/start":
            self.messages.put({"id": packet["id"], "result": {"thread": {"id": "test-thread"}}})
        elif packet.get("method") == "turn/start":
            self.messages.put({"id": packet["id"], "result": {"turn": {"id": "test-turn"}}})
            if self.request_approval:
                self.messages.put({
                    "id": 47, "method": "item/fileChange/requestApproval",
                    "params": {"reason": "Proposed edit", "threadId": "test-thread", "turnId": "test-turn"},
                })
            else:
                self._finish()
        elif packet.get("id") == 47:
            self.received.append(packet["result"]["decision"])
            self._finish()

    def _finish(self):
        self.messages.put({"method": "item/agentMessage/delta", "params": {"delta": "Finished"}})
        self.messages.put({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})

    def flush(self):
        pass

    def poll(self):
        return self.exit_code

    def kill(self):
        self.exit_code = 0
        self.messages.put(None)

    def wait(self, timeout=None):
        self.exit_code = 0
        return 0


def await_state(manager, task_id, user, expected, timeout=2):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        task = manager.get(task_id, user_id=user)
        if task.status == expected:
            return task
        time.sleep(0.01)
    raise AssertionError(f"Expected {expected}, got {task.status}")


def test_app_server_handshake_and_completed_turn(monkeypatch, tmp_path):
    proc = FakePipe()
    monkeypatch.setattr("app.codex_integration.runtime.subprocess.Popen", lambda *args, **kwargs: proc)
    manager = CodexTaskManager(executable="fake")
    task = manager.start(
        user_id="alice", project_id="project-1", conversation_id="chat-1",
        directory=tmp_path, prompt="Summarize this code", mode="readOnly",
    )
    result = await_state(manager, task.id, "alice", "completed")
    assert result.answer == "Finished"
    assert [packet.get("method") for packet in proc.writes][:4] == [
        "initialize", "initialized", "thread/start", "turn/start",
    ]
    assert proc.writes[3]["params"]["sandboxPolicy"]["type"] == "readOnly"


def test_codex_approval_is_not_automatic(monkeypatch, tmp_path):
    proc = FakePipe()
    proc.request_approval = True
    monkeypatch.setattr("app.codex_integration.runtime.subprocess.Popen", lambda *args, **kwargs: proc)
    manager = CodexTaskManager(executable="fake")
    task = manager.start(
        user_id="alice", project_id="project-1", conversation_id="chat-1",
        directory=tmp_path, prompt="Change file",
        mode="workspaceWrite", confirmed_write=True,
    )
    current = await_state(manager, task.id, "alice", "approvalRequired")
    assert proc.received == []
    approval = current.pending_approval
    assert approval is not None
    try:
        manager.approve(task.id, approval["id"], "accept", user_id="bob")
    except KeyError:
        pass
    else:
        raise AssertionError("Other user accepted pending approval")
    manager.approve(task.id, approval["id"], "decline", user_id="alice")
    await_state(manager, task.id, "alice", "completed")
    assert proc.received == ["decline"]
    assert proc.writes[3]["params"]["sandboxPolicy"]["networkAccess"] is False


def test_codex_cancel_kills_process(monkeypatch, tmp_path):
    proc = FakePipe()
    proc.request_approval = True
    monkeypatch.setattr("app.codex_integration.runtime.subprocess.Popen", lambda *args, **kwargs: proc)
    manager = CodexTaskManager(executable="fake")
    task = manager.start(
        user_id="alice", project_id="project-1", conversation_id="chat-1",
        directory=tmp_path, prompt="Change", mode="workspaceWrite", confirmed_write=True,
    )
    await_state(manager, task.id, "alice", "approvalRequired")
    manager.cancel(task.id, user_id="alice")
    await_state(manager, task.id, "alice", "cancelled")
    assert proc.poll() is not None
