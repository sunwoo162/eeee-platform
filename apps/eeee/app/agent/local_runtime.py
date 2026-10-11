"""Provider-neutral local model runtime with a bounded tool loop."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field
import httpx

from app.agent.protocol import AgentRequest, AgentResult
from app.execution.models import CommandSpec
from app.execution.runner import WorkspaceCommandRunner, WorkspaceExecutionBlocked


class LocalAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["read", "write", "run", "finish"]
    path: str | None = None
    content: str | None = None
    argv: list[str] = Field(default_factory=list)


class LocalModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1)
    actions: list[LocalAction] = Field(default_factory=list)
    done: bool = False
    next_prompt: str | None = None


class LocalModelBackend(Protocol):
    def complete(
        self, prompt: str, *, workspace: Path, context: list[dict[str, object]]
    ) -> LocalModelResponse:
        """Return one structured reasoning/action step."""


class OllamaBackend:
    """Use a local Ollama-compatible chat endpoint without an API key."""

    def __init__(self, *, model: str, base_url: str = "http://127.0.0.1:11434/api/chat", timeout: float = 120.0) -> None:
        if not model.strip():
            raise ValueError("local model name is required")
        self.model = model
        self.base_url = base_url
        self.timeout = timeout

    def complete(self, prompt: str, *, workspace: Path, context: list[dict[str, object]]) -> LocalModelResponse:
        response = httpx.post(
            self.base_url,
            json={
                "model": self.model,
                "stream": False,
                "format": "json",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are EEEE. Reply in natural Korean by default. Keep the requested JSON schema exactly.",
                    },
                    {"role": "user", "content": prompt + "\nObservations:\n" + repr(context)},
                ],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message", {}) if isinstance(payload, dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ValueError("local model response did not contain message.content")
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("local model response was not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError("local model response must be a JSON object")
        # Conversational local models commonly emit a compact finish/response
        # envelope even when asked for the tool-loop contract. Preserve that
        # response verbatim while translating it into EEEE's typed envelope;
        # project/tool responses still go through strict validation below.
        if "summary" not in decoded and isinstance(decoded.get("response"), str):
            if decoded.get("action") == "finish":
                decoded = {
                    "summary": decoded["response"],
                    "actions": [{"kind": "finish"}],
                    "done": True,
                    "next_prompt": None,
                }
        return LocalModelResponse.model_validate(decoded)


class LocalAgentRuntime:
    """Let a local model reason while EEEE owns all side effects and evidence."""

    def __init__(
        self,
        *,
        backend: LocalModelBackend,
        workspace_root: Path,
        max_steps: int = 8,
        command_timeout_seconds: float = 120.0,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.backend = backend
        self.workspace_root = workspace_root.resolve()
        self.max_steps = max_steps
        self.command_runner = WorkspaceCommandRunner(
            self.workspace_root, default_timeout_seconds=command_timeout_seconds
        )

    def run(self, request: AgentRequest) -> AgentResult:
        workspace = request.workspace.resolve()
        try:
            workspace.relative_to(self.workspace_root)
        except ValueError:
            return self._failed("Workspace is outside the local agent root")
        if not workspace.is_dir():
            return self._failed("Workspace directory does not exist")

        events: list[dict[str, object]] = []
        changed_files: list[str] = []
        test_commands: list[str] = []
        context: list[dict[str, object]] = []
        prompt = self._initial_prompt(request)
        try:
            for step in range(1, self.max_steps + 1):
                response = self.backend.complete(prompt, workspace=workspace, context=context)
                context.append({"step": step, "summary": response.summary})
                for action in response.actions:
                    observation = self._apply_action(
                        action, request, workspace, events, changed_files, test_commands
                    )
                    context.append(observation)
                if response.done or any(action.kind == "finish" for action in response.actions):
                    return AgentResult(
                        status="completed", summary=response.summary, events=events,
                        changed_files=changed_files, test_commands=test_commands, error=None,
                    )
                prompt = response.next_prompt or "Review the observations, continue the task, and return the next structured action."
            return AgentResult(
                status="failed", summary="Local agent reached its step limit", events=events,
                changed_files=changed_files, test_commands=test_commands,
                error=f"maximum local reasoning steps exceeded: {self.max_steps}",
            )
        except (ValueError, WorkspaceExecutionBlocked, OSError) as exc:
            return AgentResult(
                status="failed", summary="Local agent action was blocked", events=events,
                changed_files=changed_files, test_commands=test_commands, error=str(exc),
            )
        except Exception as exc:
            return AgentResult(
                status="failed", summary="Local agent runtime failed", events=events,
                changed_files=changed_files, test_commands=test_commands, error=str(exc),
            )

    def _apply_action(self, action, request, workspace, events, changed_files, test_commands):
        if action.kind == "finish":
            return {"type": "finish"}
        if action.kind == "read":
            self._require(request, "workspace.read")
            path = self._safe_path(workspace, action.path)
            content = path.read_text(encoding="utf-8") if path.is_file() else ""
            return {"type": "read", "path": self._relative(workspace, path), "content": content[:12000]}
        if action.kind == "write":
            self._require(request, "workspace.write")
            if action.content is None:
                raise ValueError("write action requires content")
            path = self._safe_path(workspace, action.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(action.content, encoding="utf-8", newline="\n")
            relative = self._relative(workspace, path)
            if relative not in changed_files:
                changed_files.append(relative)
            evidence = self._evidence_id(relative, action.content)
            events.append({"type": "file_write", "action": "write", "path": relative, "evidenceId": evidence})
            return {"type": "write", "path": relative, "evidenceId": evidence}
        if action.kind == "run":
            self._require(request, "command.test")
            if not action.argv or any(not isinstance(item, str) or not item for item in action.argv):
                raise ValueError("run action requires a nonempty argv")
            result = self.command_runner.run(CommandSpec(name="local-agent-test", argv=action.argv), workspace)
            command = " ".join(action.argv)
            test_commands.append(command)
            events.append({"type": "command", "command": command, "status": result.status,
                           "stdout": result.stdout, "stderr": result.stderr,
                           "evidenceId": self._evidence_id(command, result.stdout + result.stderr)})
            return {"type": "run", "command": command, "status": result.status, "stdout": result.stdout, "stderr": result.stderr}
        raise ValueError(f"unsupported local action: {action.kind}")

    @staticmethod
    def _initial_prompt(request: AgentRequest) -> str:
        return (
            "Return exactly one JSON object with this schema and no other keys: "
            '{"summary":"short Korean answer","actions":[{"kind":"finish"}],"done":true,"next_prompt":null}. '
            "For ordinary conversation, put the natural Korean reply in summary and finish immediately. "
            "For work, choose only read, write, run, or finish actions. "
            "Never use shell strings, network, package installation, deletion, or paths outside the workspace.\n"
            f"Run ID: {request.run_id}\nTask: {request.prompt}"
        )

    @staticmethod
    def _require(request: AgentRequest, action: str) -> None:
        if action not in request.allowed_actions:
            raise ValueError(f"Local agent action is not allowed: {action}")

    @staticmethod
    def _safe_path(workspace: Path, relative: str | None) -> Path:
        if not relative:
            raise ValueError("file action requires a relative path")
        path = (workspace / relative).resolve()
        try:
            path.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"path escapes workspace: {relative}") from exc
        return path

    @staticmethod
    def _relative(workspace: Path, path: Path) -> str:
        return path.relative_to(workspace).as_posix()

    @staticmethod
    def _evidence_id(subject: str, content: str) -> str:
        digest = hashlib.sha256(f"{subject}\0{content}".encode("utf-8")).hexdigest()
        return f"local-evidence-{digest[:24]}"

    @staticmethod
    def _failed(error: str) -> AgentResult:
        return AgentResult(status="failed", summary="Local agent unavailable", events=[], changed_files=[], test_commands=[], error=error)


class LocalConversationRuntime:
    """Single-turn local chat lane with no workspace tools or side effects."""

    def __init__(self, *, backend: LocalModelBackend) -> None:
        self.backend = backend

    def run(self, request: AgentRequest) -> AgentResult:
        prompt = (
            "You are EEEE, a natural Korean desktop assistant. This is ordinary conversation only. "
            "Do not read or change files, run commands, plan a project, or call tools. "
            "Answer the user's message directly and helpfully. If the user asks what you can do, "
            "briefly explain EEEE's capabilities. Do not refuse ordinary safe questions. "
            "Return exactly one JSON object with no extra keys: "
            '{"summary":"your natural Korean reply","actions":[{"kind":"finish"}],"done":true,"next_prompt":null}. '
            f"User message: {request.prompt}"
        )
        try:
            response = self.backend.complete(prompt, workspace=request.workspace, context=[])
        except Exception as exc:
            return AgentResult(
                status="unavailable", summary="Local conversation provider failed",
                events=[], changed_files=[], test_commands=[], error=str(exc),
            )
        return AgentResult(
            status="completed", summary=response.summary,
            events=[{"type": "local.conversation", "provider": "ollama"}],
            changed_files=[], test_commands=[], error=None,
        )
