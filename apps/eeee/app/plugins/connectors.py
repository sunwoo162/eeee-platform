"""Provider connector contracts used by the plugin platform."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ConnectorHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    code: str = Field(min_length=1)
    reason: str = Field(min_length=1)


@dataclass(frozen=True)
class ConnectorConnection:
    user_id: str
    plugin_id: str
    approved_permissions: frozenset[str]
    client: Any
    account_label: str | None = None


class PluginConnector(Protocol):
    plugin_id: str

    def connect(
        self, user_id: str, credential: Mapping[str, str], approved_permissions: set[str]
    ) -> ConnectorConnection: ...

    def disconnect(self, connection: ConnectorConnection) -> None: ...

    def health(self, connection: ConnectorConnection) -> ConnectorHealth: ...

    def invoke(
        self, connection: ConnectorConnection, action: str, value: dict[str, object]
    ) -> dict[str, object]: ...
