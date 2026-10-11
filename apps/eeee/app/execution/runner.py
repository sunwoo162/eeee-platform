"""Run fixed-argv commands inside a bounded project workspace."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import time

from app.execution.models import CommandResult, CommandSpec


class WorkspaceExecutionBlocked(RuntimeError):
    """Raised when a workspace cannot safely be used for command execution."""


class WorkspaceCommandRunner:
    """Execute prebuilt command specs without invoking a shell."""

    def __init__(
        self,
        workspace_root: str | Path,
        default_timeout_seconds: float = 120.0,
        max_output_chars: int = 8_000,
    ):
        if default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be positive")
        if max_output_chars <= 0:
            raise ValueError("max_output_chars must be positive")
        self.workspace_root = Path(workspace_root).resolve()
        self.default_timeout_seconds = default_timeout_seconds
        self.max_output_chars = max_output_chars

    def run(self, spec: CommandSpec, workspace: str | Path) -> CommandResult:
        resolved_workspace = self._validate_workspace(workspace)
        if not spec.name or not spec.argv:
            raise ValueError("command specs require a name and argv")
        timeout = (
            spec.timeout_seconds
            if spec.timeout_seconds is not None
            else self.default_timeout_seconds
        )
        if timeout <= 0:
            raise ValueError("command timeout must be positive")

        started = time.perf_counter()
        argv = self._resolve_argv(list(spec.argv))
        try:
            completed = subprocess.run(
                argv,
                cwd=str(resolved_workspace),
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout, stdout_truncated = self._truncate(exc.output)
            stderr, stderr_truncated = self._truncate(exc.stderr)
            return CommandResult(
                name=spec.name,
                argv=tuple(argv),
                status="timeout",
                exit_code=None,
                duration_ms=self._duration_ms(started),
                stdout=stdout,
                stderr=stderr,
                truncated=stdout_truncated or stderr_truncated,
            )

        stdout, stdout_truncated = self._truncate(completed.stdout)
        stderr, stderr_truncated = self._truncate(completed.stderr)
        return CommandResult(
            name=spec.name,
            argv=tuple(argv),
            status="passed" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            duration_ms=self._duration_ms(started),
            stdout=stdout,
            stderr=stderr,
            truncated=stdout_truncated or stderr_truncated,
        )

    @staticmethod
    def _resolve_argv(argv: list[str]) -> list[str]:
        """Resolve tool names for packaged Windows processes without a shell."""
        if not argv or not argv[0] or Path(argv[0]).name != argv[0]:
            return argv
        executable = argv[0]
        resolved = shutil.which(executable)
        if resolved:
            argv[0] = resolved
            return argv
        if os.name == "nt":
            program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            candidates = {
                "node": program_files / "nodejs" / "node.exe",
                "node.exe": program_files / "nodejs" / "node.exe",
                "npm": program_files / "nodejs" / "npm.cmd",
                "npm.cmd": program_files / "nodejs" / "npm.cmd",
                "python": Path(sys.executable),
                "python.exe": Path(sys.executable),
            }
            candidate = candidates.get(executable.casefold())
            if candidate is not None and candidate.exists():
                argv[0] = str(candidate)
        return argv

    def _validate_workspace(self, workspace: str | Path) -> Path:
        resolved_workspace = Path(workspace).resolve()
        try:
            resolved_workspace.relative_to(self.workspace_root)
        except ValueError as exc:
            raise WorkspaceExecutionBlocked(
                f"Workspace is outside the allowed root: {resolved_workspace}"
            ) from exc
        if not resolved_workspace.is_dir():
            raise WorkspaceExecutionBlocked(
                f"Workspace directory does not exist: {resolved_workspace}"
            )
        return resolved_workspace

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, round((time.perf_counter() - started) * 1000))

    def _truncate(self, value: str | bytes | None) -> tuple[str, bool]:
        if value is None:
            return "", False
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return value[: self.max_output_chars], len(value) > self.max_output_chars
