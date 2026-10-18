"""Provider metadata and factories for the first EEEE connector set."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import base64
from email.message import EmailMessage
from email import policy
import json
from typing import Any

import httpx

from pydantic import BaseModel, ConfigDict, Field

from app.plugins.oauth import OAuthProviderConfig
from app.plugins.connectors import ConnectorConnection
from app.plugins.protocol_connectors import (
    HttpOpenApiConnector,
    HttpOperation,
    HttpTransport,
    HttpxTransport,
    _health_from_status,
)


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    base_url: str = Field(alias="baseUrl", min_length=1)
    oauth: OAuthProviderConfig
    health_path: str | None = Field(default=None, alias="healthPath")


@dataclass(frozen=True)
class ProviderSpec:
    plugin_id: str
    health_path: str
    operations: Mapping[str, HttpOperation]


class GmailConnector(HttpOpenApiConnector):
    """Gmail's list/send APIs with the small provider-specific normalization EEEE needs.

    The generic OpenAPI connector is intentionally kept generic. Gmail is the
    first connector that needs a second request (message metadata) and an
    RFC822 envelope, so those details live here instead of leaking into the
    router or kernel.
    """

    _METADATA_HEADERS = ["From", "Subject", "Date"]

    def invoke(
        self, connection: ConnectorConnection, action: str, value: dict[str, object]
    ) -> dict[str, object]:
        if action == "mail.list":
            return self._list_messages(connection, value)
        if action == "mail.send":
            return self._send_message(connection, value)
        return super().invoke(connection, action, value)

    def _list_messages(
        self, connection: ConnectorConnection, value: Mapping[str, object]
    ) -> dict[str, object]:
        self._require_permission(connection, "mail.read")
        limit = value.get("limit", 10)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("mail list limit must be an integer")
        limit = max(1, min(limit, 20))
        query = value.get("query")
        if query is not None and not isinstance(query, str):
            raise ValueError("mail list query must be a string")
        params: dict[str, object] = {"maxResults": limit}
        if isinstance(query, str) and query.strip():
            params["q"] = query.strip()
        listing = self._request_json(
            connection,
            "GET",
            "/users/me/messages",
            params=params,
        )
        raw_messages = listing.get("messages", [])
        if not isinstance(raw_messages, list):
            raise ValueError("Gmail message list response is invalid")
        messages: list[dict[str, object]] = []
        for raw in raw_messages[:limit]:
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
                continue
            metadata = self._request_json(
                connection,
                "GET",
                f"/users/me/messages/{raw['id']}",
                params={
                    "format": "metadata",
                    "metadataHeaders": self._METADATA_HEADERS,
                },
            )
            messages.append(self._normalize_message(metadata, fallback=raw))
        next_page = listing.get("nextPageToken")
        result: dict[str, object] = {"messages": messages}
        if isinstance(next_page, str) and next_page:
            result["nextPageToken"] = next_page
        return result

    def _send_message(
        self, connection: ConnectorConnection, value: Mapping[str, object]
    ) -> dict[str, object]:
        self._require_permission(connection, "mail.send")
        raw = value.get("raw")
        if raw is None:
            to = _required_text(value, "to", "받는 사람")
            subject = _required_text(value, "subject", "제목")
            body = _required_text(value, "body", "본문")
            _reject_header_control_characters(to, "받는 사람")
            _reject_header_control_characters(subject, "제목")
            message = EmailMessage(policy=policy.SMTP)
            message["To"] = to
            message["Subject"] = subject
            message.set_content(body)
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        elif not isinstance(raw, str) or not raw:
            raise ValueError("메일 raw 값이 올바르지 않습니다")
        sent = self._request_json(
            connection,
            "POST",
            "/users/me/messages/send",
            json={"raw": raw},
        )
        result: dict[str, object] = {"sent": True}
        for key in ("id", "threadId"):
            if isinstance(sent.get(key), str):
                result[key] = sent[key]
        return result

    def _request_json(
        self,
        connection: ConnectorConnection,
        method: str,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        json: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        response = self.transport.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(connection),
            params=params,
            json=json,
        )
        health = _health_from_status(self.plugin_id, response.status_code)
        if health.status != "healthy":
            raise RuntimeError(health.reason)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("provider response must be an object")
        return payload

    @staticmethod
    def _require_permission(connection: ConnectorConnection, permission: str) -> None:
        if permission not in connection.approved_permissions:
            raise PermissionError(f"permission is required: {permission}")

    @classmethod
    def _normalize_message(
        cls, payload: Mapping[str, Any], *, fallback: Mapping[str, object]
    ) -> dict[str, object]:
        headers: dict[str, str] = {}
        payload_section = payload.get("payload")
        payload_headers = payload_section.get("headers", []) if isinstance(payload_section, dict) else []
        if isinstance(payload_headers, list):
            for item in payload_headers:
                if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("value"), str):
                    headers[item["name"].casefold()] = item["value"]
        labels = payload.get("labelIds", [])
        labels = labels if isinstance(labels, list) else []
        return {
            "id": payload.get("id") or fallback.get("id"),
            "threadId": payload.get("threadId") or fallback.get("threadId"),
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": str(payload.get("snippet") or ""),
            "isUnread": "UNREAD" in labels,
        }


def build_gmail_connector(base_url: str, transport: HttpTransport) -> GmailConnector:
    return GmailConnector(
        "gmail",
        base_url=base_url,
        transport=transport,
        operations=_SPECS["gmail"].operations,
        health_path=_SPECS["gmail"].health_path,
    )


def _operation(method: str, path: str, permission: str) -> HttpOperation:
    return HttpOperation(method=method, path=path, permission=permission)


def _required_text(value: Mapping[str, object], key: str, label: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"메일 {label}이(가) 필요합니다")
    return raw.strip()


def _reject_header_control_characters(value: str, label: str) -> None:
    if "\r" in value or "\n" in value:
        raise ValueError(f"메일 {label}에 허용되지 않는 문자가 있습니다")


def _refresh_oauth_credential(
    credential: Mapping[str, str], config: OAuthProviderConfig
) -> Mapping[str, str]:
    refresh_token = credential.get("refresh_token")
    if not refresh_token:
        raise ValueError("provider refresh token is unavailable")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": config.client_id,
    }
    if config.client_secret:
        data["client_secret"] = config.client_secret
    try:
        response = httpx.post(config.token_endpoint, data=data, timeout=15.0)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("provider credential refresh failed") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
        raise RuntimeError("provider credential refresh returned no access token")
    return {
        **dict(credential),
        **{
            key: str(value)
            for key, value in payload.items()
            if isinstance(value, (str, int, float, bool))
        },
    }


_SPECS = {
    "gmail": ProviderSpec(
        "gmail", "/users/me/profile", {
            "mail.list": _operation("GET", "/users/me/messages", "mail.read"),
            "mail.send": _operation("POST", "/users/me/messages/send", "mail.send"),
        },
    ),
    "google-calendar": ProviderSpec(
        "google-calendar", "/users/me/calendarList", {
            "calendar.events": _operation("GET", "/calendars/primary/events", "calendar.read"),
            "calendar.create": _operation("POST", "/calendars/primary/events", "calendar.write"),
        },
    ),
    "google-drive": ProviderSpec(
        "google-drive", "/about?fields=user", {
            "files.list": _operation("GET", "/files", "files.read"),
            "files.create": _operation("POST", "/files", "files.write"),
        },
    ),
    "google-contacts": ProviderSpec(
        "google-contacts", "/v1/people/me?personFields=names", {
            "contacts.list": _operation("GET", "/v1/people/me/connections", "contacts.read"),
        },
    ),
    "github": ProviderSpec(
        "github", "/user", {
            "repos.list": _operation("GET", "/user/repos", "repos.read"),
            "issues.list": _operation("GET", "/issues", "issues.read"),
            "pull_requests.write": _operation("POST", "/repos/{owner}/{repo}/pulls", "pull_requests.write"),
        },
    ),
    "figma": ProviderSpec(
        "figma", "/me", {
            "files.get": _operation("GET", "/files/{file_key}", "files.read"),
            "files.write": _operation("PUT", "/files/{file_key}", "files.write"),
        },
    ),
    "slack": ProviderSpec(
        "slack", "/api/auth.test", {
            "messages.list": _operation("GET", "/api/conversations.history", "messages.read"),
            "messages.send": _operation("POST", "/api/chat.postMessage", "messages.write"),
        },
    ),
    "linear": ProviderSpec(
        "linear", "/graphql", {
            "issues.search": _operation("POST", "/graphql", "issues.read"),
            "issues.create": _operation("POST", "/graphql", "issues.write"),
        },
    ),
    "todoist": ProviderSpec(
        "todoist", "/rest/v2/projects", {
            "tasks.list": _operation("GET", "/rest/v2/tasks", "tasks.read"),
            "tasks.create": _operation("POST", "/rest/v2/tasks", "tasks.write"),
        },
    ),
    "outlook-email": ProviderSpec(
        "outlook-email", "/v1.0/me", {
            "mail.list": _operation("GET", "/v1.0/me/messages", "mail.read"),
            "mail.send": _operation("POST", "/v1.0/me/sendMail", "mail.send"),
        },
    ),
    "outlook-calendar": ProviderSpec(
        "outlook-calendar", "/v1.0/me", {
            "calendar.events": _operation("GET", "/v1.0/me/events", "calendar.read"),
            "calendar.create": _operation("POST", "/v1.0/me/events", "calendar.write"),
        },
    ),
}

INITIAL_PROVIDER_IDS = frozenset(_SPECS)


def build_gmail_provider_config(client_id: str, client_secret: str | None = None) -> ProviderConfig:
    """Build the first-party Gmail profile from operator-only client settings."""

    return ProviderConfig(
        baseUrl="https://gmail.googleapis.com/gmail/v1",
        healthPath=_SPECS["gmail"].health_path,
        oauth=OAuthProviderConfig(
            authorizationEndpoint="https://accounts.google.com/o/oauth2/v2/auth",
            tokenEndpoint="https://oauth2.googleapis.com/token",
            clientId=client_id,
            clientSecret=client_secret,
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
            ],
            scopeByPermission={
                "mail.read": ["https://www.googleapis.com/auth/gmail.readonly"],
                "mail.send": ["https://www.googleapis.com/auth/gmail.send"],
            },
            authorizationParams={
                "access_type": "offline",
                "include_granted_scopes": "true",
            },
        ),
    )


def load_provider_configs(
    raw: str | None,
    *,
    gmail_client_id: str | None = None,
    gmail_client_secret: str | None = None,
) -> dict[str, ProviderConfig]:
    if raw is None or not raw.strip():
        configs: dict[str, ProviderConfig] = {}
    else:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("EEEE_PLUGIN_PROVIDER_CONFIG_JSON is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("EEEE_PLUGIN_PROVIDER_CONFIG_JSON must be an object")
        configs = {
            plugin_id: ProviderConfig.model_validate(config)
            for plugin_id, config in payload.items()
        }
    if gmail_client_id and "gmail" not in configs:
        configs["gmail"] = build_gmail_provider_config(gmail_client_id, gmail_client_secret)
    return configs


def build_provider_connectors(
    configs: Mapping[str, ProviderConfig],
    *,
    transport: HttpTransport | None = None,
) -> dict[str, HttpOpenApiConnector]:
    """Build only explicitly configured, known provider connectors."""

    unknown = set(configs) - set(_SPECS)
    if unknown:
        raise ValueError(f"unknown provider configuration: {sorted(unknown)}")
    selected_transport = transport or HttpxTransport()
    connectors: dict[str, HttpOpenApiConnector] = {}
    for plugin_id, config in configs.items():
        if plugin_id == "gmail":
            connectors[plugin_id] = GmailConnector(
                plugin_id,
                base_url=config.base_url,
                transport=selected_transport,
                operations=_SPECS[plugin_id].operations,
                health_path=config.health_path or _SPECS[plugin_id].health_path,
                credential_refresher=lambda credential, oauth=config.oauth: _refresh_oauth_credential(credential, oauth),
            )
        else:
            connectors[plugin_id] = HttpOpenApiConnector(
                plugin_id,
                base_url=config.base_url,
                transport=selected_transport,
                operations=_SPECS[plugin_id].operations,
                health_path=config.health_path or _SPECS[plugin_id].health_path,
                credential_refresher=lambda credential, oauth=config.oauth: _refresh_oauth_credential(credential, oauth),
            )
    return connectors
