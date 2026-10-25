"""Contracts shared by coding-agent runtime adapters."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class AgentRequest:
    prompt: str
    workspace: Path
    allowed_actions: list[str]
    run_id: str
    user_id: str = "local-user"
    conversation_id: str | None = None


@dataclass(frozen=True)
class AgentResult:
    status: str
    summary: str
    events: list[dict[str, object]]
    changed_files: list[str]
    test_commands: list[str]
    error: str | None
    error_code: str | None = None


class AgentRuntime(Protocol):
    def run(self, request: AgentRequest) -> AgentResult:
        """Execute one approved agent request and return structured evidence."""
