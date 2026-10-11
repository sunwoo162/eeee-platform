import subprocess
import sys
import os

import pytest

from app.execution.models import CommandSpec
from app.execution.runner import WorkspaceCommandRunner, WorkspaceExecutionBlocked


def test_runner_executes_fixed_argv_without_shell_and_captures_success(tmp_path, monkeypatch):
    workspace = tmp_path / "root" / "project"
    workspace.mkdir(parents=True)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "compiled\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = WorkspaceCommandRunner(tmp_path / "root").run(
        CommandSpec("compileall", (sys.executable, "-m", "compileall", ".")),
        workspace,
    )

    assert result.status == "passed"
    assert result.exit_code == 0
    assert result.stdout == "compiled\n"
    assert result.stderr == ""
    assert len(calls) == 1
    assert calls[0][0] == [sys.executable, "-m", "compileall", "."]
    assert calls[0][1]["cwd"] == str(workspace)
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["text"] is True


def test_runner_resolves_windows_node_when_path_is_not_available(tmp_path, monkeypatch):
    runner = WorkspaceCommandRunner(tmp_path)
    monkeypatch.setattr("app.execution.runner.shutil.which", lambda _name: None)
    if os.name != "nt":
        pytest.skip("Windows executable resolution is platform-specific")

    resolved = runner._resolve_argv(["node", "--check", "src/app.js"])

    assert resolved[0].lower().endswith("node.exe")


def test_runner_rejects_workspace_outside_allowed_root_before_starting_process(
    tmp_path, monkeypatch
):
    allowed_root = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed_root.mkdir()
    outside.mkdir()
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(WorkspaceExecutionBlocked):
        WorkspaceCommandRunner(allowed_root).run(
            CommandSpec("check", (sys.executable, "-c", "pass")), outside
        )

    assert called is False


def test_runner_rejects_symlinked_workspace_that_resolves_outside_root(tmp_path):
    allowed_root = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed_root.mkdir()
    outside.mkdir()
    link = allowed_root / "project-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable in this Windows environment")

    with pytest.raises(WorkspaceExecutionBlocked):
        WorkspaceCommandRunner(allowed_root).run(
            CommandSpec("check", (sys.executable, "-c", "pass")), link
        )


def test_runner_marks_nonzero_exit_as_failed(tmp_path, monkeypatch):
    workspace = tmp_path / "root" / "project"
    workspace.mkdir(parents=True)

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 3, "partial", "bad input")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = WorkspaceCommandRunner(tmp_path / "root").run(
        CommandSpec("tests", (sys.executable, "-m", "pytest", "-q")), workspace
    )

    assert result.status == "failed"
    assert result.exit_code == 3
    assert result.stdout == "partial"
    assert result.stderr == "bad input"


def test_runner_marks_timeout_and_limits_output(tmp_path, monkeypatch):
    workspace = tmp_path / "root" / "project"
    workspace.mkdir(parents=True)
    long_stdout = "o" * 9_000
    long_stderr = "e" * 9_000

    def fake_run(argv, **kwargs):
        assert kwargs["timeout"] == 0.5
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=long_stdout, stderr=long_stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = WorkspaceCommandRunner(
        tmp_path / "root", default_timeout_seconds=0.5, max_output_chars=8_000
    ).run(CommandSpec("slow", (sys.executable, "-c", "pass")), workspace)

    assert result.status == "timeout"
    assert result.exit_code is None
    assert len(result.stdout) == 8_000
    assert len(result.stderr) == 8_000
    assert result.truncated is True


def test_runner_rejects_nonpositive_command_timeout(tmp_path):
    workspace = tmp_path / "root" / "project"
    workspace.mkdir(parents=True)

    with pytest.raises(ValueError, match="command timeout must be positive"):
        WorkspaceCommandRunner(tmp_path / "root").run(
            CommandSpec("invalid", (sys.executable, "-c", "pass"), timeout_seconds=0),
            workspace,
        )
