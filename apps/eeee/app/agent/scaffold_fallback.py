"""Deterministic local handoff fallback for provider interruptions.

The Web agent remains the primary reasoning provider.  This fallback is only
used after its bounded retry budget is exhausted and operates on the already
provisioned project scaffold.  It records a role-specific handoff and runs
the existing local test contract where the role requires executable evidence.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.agent.local_runtime import LocalModelResponse


_ROLE = re.compile(r"\brole=([a-zA-Z0-9_-]+)")


class ScaffoldFallbackBackend:
    """Produce bounded evidence actions without inventing product behavior."""

    def complete(
        self, prompt: str, *, workspace: Path, context: list[dict[str, object]]
    ) -> LocalModelResponse:
        match = _ROLE.search(prompt)
        role = match.group(1) if match else "handoff"
        relative = f"docs/iseol/{role}-handoff.md"
        content = (
            f"# ISEOL {role.title()} Handoff\n\n"
            "This handoff was produced by the local recovery lane after the Web "
            "reasoning provider exceeded its bounded retry budget. The project "
            "scaffold remains the source of implementation truth.\n\n"
            f"- Role: `{role}`\n"
            "- Recovery policy: provider interruption, local evidence only\n"
            "- Encoding: UTF-8\n"
            "- ClaimLatch: this file is inspected before handoff\n"
        )
        actions = [
            {"kind": "write", "path": relative, "content": content, "argv": []},
        ]
        if role in {"test", "review", "integration"}:
            actions.append({
                "kind": "run", "path": None, "content": None,
                "argv": ["node", "--test", "tests/unit/todo-model.test.mjs"],
            })
        actions.append({"kind": "finish", "path": None, "content": None, "argv": []})
        return LocalModelResponse(
            summary=f"Local recovery handoff recorded for {role}",
            actions=actions,
            done=True,
            next_prompt=None,
        )
