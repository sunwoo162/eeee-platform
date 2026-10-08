"""Small HTTP client used by the desktop shell."""

import httpx


class ApiError(RuntimeError):
    """The local coordinator returned an error response."""


class PetApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", project_id: str = "default"):
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id

    def _request(self, method: str, path: str, **kwargs) -> dict[str, object]:
        response = httpx.request(method, f"{self.base_url}{path}", timeout=5.0, **kwargs)
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ApiError(str(detail))
        return response.json()

    def get_state(self) -> dict[str, object]:
        return self._request("GET", f"/projects/{self.project_id}/state")

    def get_health(self) -> dict[str, object]:
        return self._request("GET", "/health")

    def get_desktop_state(self, project_id: str | None = None) -> dict[str, object]:
        kwargs: dict[str, object] = {}
        if project_id is not None:
            kwargs["params"] = {"projectId": project_id}
        return self._request("GET", "/api/desktop/state", **kwargs)

    def get_desktop_events(self, cursor: int = 0) -> dict[str, object]:
        return self._request(
            "GET", "/api/desktop/events", params={"cursor": cursor}
        )

    def route_assistant(
        self, text: str, workspace: str | None = None
    ) -> dict[str, object]:
        payload: dict[str, object] = {"text": text}
        if workspace is not None:
            payload["workspace"] = workspace
        return self._request("POST", "/api/assistant/route", json=payload)

    def open_project(self, project_id: str) -> dict[str, object]:
        """Load the durable organization map for a project in the Desktop view."""
        if not project_id.strip():
            raise ValueError("project_id is required")
        return self._request("GET", f"/api/projects/{project_id}/map")

    def issue_pairing_code(self) -> dict[str, object]:
        return self._request("POST", "/api/desktop/pairing/code")

    def create_request(self, text: str) -> dict[str, object]:
        return self._request(
            "POST",
            f"/projects/{self.project_id}/requests",
            json={"text": text},
        )

    def approve(self, request_id: str, selected: list[str]) -> dict[str, object]:
        return self._request(
            "POST",
            f"/projects/{self.project_id}/decisions/{request_id}/approve",
            json={"selected": selected},
        )

    def advance(self, task_id: str) -> dict[str, object]:
        return self._request(
            "POST", f"/projects/{self.project_id}/tasks/{task_id}/advance"
        )

    def run(self, task_id: str) -> dict[str, object]:
        return self._request(
            "POST", f"/projects/{self.project_id}/tasks/{task_id}/run"
        )

    def retry(self, task_id: str) -> dict[str, object]:
        return self._request(
            "POST", f"/projects/{self.project_id}/tasks/{task_id}/retry"
        )


# Backwards-compatible name for the canonical Desktop HTTP client.
DesktopApiClient = PetApiClient
