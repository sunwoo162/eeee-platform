"""HTTP clients used by the thin Desktop shell."""

from collections.abc import Iterator
import json

import httpx
from typing import Any


class ApiError(RuntimeError):
    """The local coordinator returned an error response."""


class PetApiClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        project_id: str = "default",
        *,
        assistant_timeout_seconds: float = 180.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self.assistant_timeout_seconds = assistant_timeout_seconds

    def _request(
        self, method: str, path: str, *, timeout: float = 5.0, **kwargs
    ) -> Any:
        response = httpx.request(method, f"{self.base_url}{path}", timeout=timeout, **kwargs)
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ApiError(str(detail))
        if response.status_code == 204:
            return {}
        return response.json()

    @staticmethod
    def _plugin_path(plugin_id: str, suffix: str = "") -> str:
        plugin_id = plugin_id.strip()
        if not plugin_id or "/" in plugin_id or "\\" in plugin_id:
            raise ValueError("plugin_id must be a non-empty path segment")
        return f"/api/plugins/{plugin_id}{suffix}"

    def get_plugin_catalog(self) -> list[dict[str, object]]:
        result = self._request("GET", "/api/plugins/catalog")
        if not isinstance(result, list):
            raise ApiError("Plugin catalog response was not a list")
        return [item for item in result if isinstance(item, dict)]

    def install_plugin(self, plugin_id: str) -> dict[str, object]:
        result = self._request("POST", self._plugin_path(plugin_id, "/install"))
        if not isinstance(result, dict):
            raise ApiError("Plugin install response was not an object")
        return result

    def get_plugin_connection(self, plugin_id: str) -> dict[str, object]:
        result = self._request("GET", self._plugin_path(plugin_id, "/connection"))
        if not isinstance(result, dict):
            raise ApiError("Plugin connection response was not an object")
        return result

    def start_plugin_oauth(
        self,
        plugin_id: str,
        approved_permissions: list[str],
        account_label: str | None = None,
    ) -> dict[str, object]:
        result = self._request(
            "POST",
            self._plugin_path(plugin_id, "/oauth/start"),
            json={
                "approvedPermissions": list(approved_permissions),
                "accountLabel": account_label,
            },
        )
        if not isinstance(result, dict):
            raise ApiError("Plugin OAuth response was not an object")
        return result

    def connect_plugin(
        self,
        plugin_id: str,
        credential: dict[str, str],
        approved_permissions: list[str],
        account_label: str | None = None,
    ) -> dict[str, object]:
        result = self._request(
            "POST",
            self._plugin_path(plugin_id, "/connect"),
            json={
                "credential": credential,
                "approvedPermissions": list(approved_permissions),
                "accountLabel": account_label,
            },
        )
        if not isinstance(result, dict):
            raise ApiError("Plugin connection response was not an object")
        return result

    def disconnect_plugin(self, plugin_id: str) -> dict[str, object]:
        result = self._request("POST", self._plugin_path(plugin_id, "/disconnect"))
        if not isinstance(result, dict):
            raise ApiError("Plugin disconnect response was not an object")
        return result

    def pause_plugin(self, plugin_id: str) -> dict[str, object]:
        result = self._request("POST", self._plugin_path(plugin_id, "/pause"))
        if not isinstance(result, dict):
            raise ApiError("Plugin pause response was not an object")
        return result

    def resume_plugin(self, plugin_id: str) -> dict[str, object]:
        result = self._request("POST", self._plugin_path(plugin_id, "/resume"))
        if not isinstance(result, dict):
            raise ApiError("Plugin resume response was not an object")
        return result

    def uninstall_plugin(self, plugin_id: str) -> dict[str, object]:
        result = self._request("DELETE", self._plugin_path(plugin_id, "/install"))
        if result == {}:
            return {"pluginId": plugin_id, "status": "not_installed"}
        if not isinstance(result, dict):
            raise ApiError("Plugin uninstall response was not an object")
        return result

    def get_plugin_oauth_status(self, plugin_id: str, state: str) -> dict[str, object]:
        if not state.strip():
            raise ValueError("oauth state is required")
        result = self._request(
            "GET", self._plugin_path(plugin_id, "/oauth/status"),
            params={"state": state},
        )
        if not isinstance(result, dict):
            raise ApiError("Plugin OAuth status response was not an object")
        return result

    def get_plugin_launch_info(self, plugin_id: str) -> dict[str, object]:
        result = self._request("GET", self._plugin_path(plugin_id, "/launch"))
        if not isinstance(result, dict):
            raise ApiError("Plugin launch response was not an object")
        return result

    @staticmethod
    def _conversation_path(conversation_id: str) -> str:
        conversation_id = conversation_id.strip()
        if not conversation_id or "/" in conversation_id or "\\" in conversation_id:
            raise ValueError("conversation_id must be a non-empty path segment")
        return f"/api/assistant/conversations/{conversation_id}"

    def get_conversations(self, *, query: str = "", limit: int = 50) -> list[dict[str, object]]:
        result = self._request(
            "GET",
            "/api/assistant/conversations",
            params={"query": query, "limit": limit},
        )
        if not isinstance(result, list):
            raise ApiError("Conversation list response was not a list")
        return [item for item in result if isinstance(item, dict)]

    def get_conversation(
        self,
        conversation_id: str = "desktop-default",
        *,
        limit: int = 100,
        before_id: int | None = None,
    ) -> dict[str, object]:
        params: dict[str, object] = {"limit": limit}
        if before_id is not None:
            params["beforeId"] = before_id
        result = self._request(
            "GET", self._conversation_path(conversation_id), params=params
        )
        if not isinstance(result, dict):
            raise ApiError("Conversation response was not an object")
        return result

    def send_conversation_message(
        self,
        text: str,
        *,
        conversation_id: str = "desktop-default",
        workspace: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "text": text,
            "conversationId": conversation_id,
        }
        if workspace is not None:
            payload["workspace"] = workspace
        result = self._request(
            "POST",
            "/api/assistant/route",
            json=payload,
            timeout=self.assistant_timeout_seconds,
        )
        if not isinstance(result, dict):
            raise ApiError("Assistant response was not an object")
        return result

    def get_state(self) -> dict[str, object]:
        return self._request("GET", f"/projects/{self.project_id}/state")

    def get_health(self) -> dict[str, object]:
        return self._request("GET", "/health")

    def get_runtime_status(self) -> dict[str, object]:
        return self._request("GET", "/v1/runtime")

    def create_conversation(self, title: str = "새 대화") -> dict[str, object]:
        return self._request("POST", "/v1/conversations", json={"title": title})

    def list_conversations(self, limit: int = 50) -> dict[str, object]:
        return self._request("GET", "/v1/conversations", params={"limit": limit})

    def get_conversation_messages(
        self, conversation_id: str, *, after_sequence: int = 0, limit: int = 100
    ) -> dict[str, object]:
        return self._request(
            "GET",
            f"/v1/conversations/{conversation_id}/messages",
            params={"afterSequence": after_sequence, "limit": limit},
        )

    def submit_turn(
        self, conversation_id: str, content: str, client_message_id: str
    ) -> dict[str, object]:
        return self._request(
            "POST",
            f"/v1/conversations/{conversation_id}/turns",
            json={"clientMessageId": client_message_id, "content": content},
        )

    def stream_request_events(
        self,
        request_id: str,
        *,
        after_sequence: int = 0,
        timeout_seconds: float = 60.0,
    ) -> Iterator[dict[str, object]]:
        with httpx.stream(
            "GET",
            f"{self.base_url}/v1/requests/{request_id}/events",
            params={
                "afterSequence": after_sequence,
                "timeoutSeconds": timeout_seconds,
            },
            timeout=timeout_seconds + 5,
        ) as response:
            if response.is_error:
                try:
                    detail = response.json().get("detail", response.text)
                except ValueError:
                    detail = response.text
                raise ApiError(str(detail))
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError as exc:
                    raise ApiError("Core returned an invalid conversation event") from exc
                if isinstance(event, dict):
                    yield event

    def cancel_request(self, request_id: str) -> dict[str, object]:
        return self._request("POST", f"/v1/requests/{request_id}/cancel")

    def retry_request(self, request_id: str) -> dict[str, object]:
        return self._request("POST", f"/v1/requests/{request_id}/retry")

    @staticmethod
    def chatgpt_login_url() -> str:
        """Return the browser login page used by the local ChatGPT runtime."""
        return "https://chatgpt.com/auth/login"

    def get_desktop_state(self, project_id: str | None = None) -> dict[str, object]:
        kwargs: dict[str, object] = {}
        if project_id is not None:
            kwargs["params"] = {"projectId": project_id}
        return self._request("GET", "/api/desktop/state", **kwargs)

    def get_desktop_events(self, cursor: int = 0) -> dict[str, object]:
        return self._request(
            "GET", "/api/desktop/events", params={"cursor": cursor}
        )

    def get_plugin_executions(self, limit: int = 20) -> dict[str, object]:
        return self._request(
            "GET", "/api/desktop/plugin-executions", params={"limit": limit}
        )

    def route_assistant(
        self, text: str, workspace: str | None = None, *, approved: bool = False,
        approval_request_id: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {"text": text}
        if workspace is not None:
            payload["workspace"] = workspace
        if approved:
            payload["approved"] = True
        if approval_request_id is not None:
            payload["approvalRequestId"] = approval_request_id
        return self._request(
            "POST", "/api/assistant/route", json=payload,
            timeout=self.assistant_timeout_seconds,
        )

    def open_project(self, project_id: str) -> dict[str, object]:
        """Load the durable organization map for a project in the Desktop view."""
        if not project_id.strip():
            raise ValueError("project_id is required")
        return self._request("GET", f"/api/projects/{project_id}/map")

    def get_assistant_job(self, job_id: str) -> dict[str, object]:
        if not job_id.strip():
            raise ValueError("job_id is required")
        return self._request("GET", f"/api/assistant/jobs/{job_id}")

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
