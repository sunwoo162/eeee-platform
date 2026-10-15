"""Provider metadata and factories for the first EEEE connector set."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json

from pydantic import BaseModel, ConfigDict, Field

from app.plugins.oauth import OAuthProviderConfig
from app.plugins.protocol_connectors import (
    HttpOpenApiConnector,
    HttpOperation,
    HttpTransport,
    HttpxTransport,
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


def _operation(method: str, path: str, permission: str) -> HttpOperation:
    return HttpOperation(method=method, path=path, permission=permission)


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
    return {
        plugin_id: HttpOpenApiConnector(
            plugin_id,
            base_url=config.base_url,
            transport=selected_transport,
            operations=_SPECS[plugin_id].operations,
            health_path=config.health_path or _SPECS[plugin_id].health_path,
        )
        for plugin_id, config in configs.items()
    }
