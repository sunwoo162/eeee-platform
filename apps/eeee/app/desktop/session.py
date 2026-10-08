"""Headless Desktop control-plane state and commands."""

from __future__ import annotations

from typing import Any


class DesktopSession:
    """Keep the Desktop presentation model separate from the Qt window."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.project_id: str | None = None
        self.snapshot: dict[str, object] = {}

    def refresh(self, project_id: str | None = None) -> dict[str, object]:
        if project_id is not None:
            self.project_id = project_id
        self.snapshot = self.client.get_desktop_state(self.project_id)
        return self.snapshot

    def route(self, text: str, workspace: str | None = None) -> dict[str, object]:
        if self.project_id is not None:
            try:
                result = self.client.route_assistant(text, workspace, self.project_id)
            except TypeError:
                # Keep compatibility with small headless test clients and older bridges.
                result = self.client.route_assistant(text, workspace)
        else:
            result = self.client.route_assistant(text, workspace)
        selected_project = result.get("project_id")
        if isinstance(selected_project, str) and selected_project:
            self.project_id = selected_project
        snapshot = self.refresh()
        snapshot["assistantRoute"] = result
        if not isinstance(selected_project, str) or not selected_project:
            # A direct EEEE/plugin response has no project snapshot to carry
            # its state. Projectless responses must still be visible in the
            # pet bubble instead of being overwritten by the default project.
            route_status = result.get("status")
            state = {
                "completed": "completed",
                "blocked": "blocked",
                "plugin_required": "blocked",
                "needs_clarification": "idle",
            }.get(route_status, "idle")
            snapshot.update({
                "state": state,
                "message": result.get("message", "EEEE가 응답을 준비했어."),
            })
        self.snapshot = snapshot
        return snapshot

    def issue_pairing_code(self) -> dict[str, object]:
        result = self.client.issue_pairing_code()
        return _without_secrets(result)


def _without_secrets(value: dict[str, object]) -> dict[str, object]:
    return {
        key: item
        for key, item in value.items()
        if key.replace("_", "").lower() not in {"accesstoken", "token", "password"}
    }
