"""Provider-neutral OAuth Authorization Code + PKCE session broker."""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field


class OAuthError(RuntimeError):
    """Base error for user-actionable OAuth failures."""


class OAuthStateMismatch(OAuthError):
    pass


class OAuthCancelled(OAuthError):
    pass


class OAuthProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    authorization_endpoint: str = Field(alias="authorizationEndpoint", min_length=1)
    token_endpoint: str = Field(alias="tokenEndpoint", min_length=1)
    client_id: str = Field(alias="clientId", min_length=1)
    client_secret: str | None = Field(default=None, alias="clientSecret", repr=False)
    scopes: list[str] = Field(min_length=1)
    scope_by_permission: dict[str, list[str]] = Field(
        default_factory=dict, alias="scopeByPermission"
    )
    authorization_params: dict[str, str] = Field(
        default_factory=dict, alias="authorizationParams"
    )

    def scopes_for_permissions(self, approved_permissions: set[str] | frozenset[str]) -> list[str]:
        """Return only the provider scopes needed by the approved EEEE permissions."""

        if not approved_permissions or not self.scope_by_permission:
            # Preserve the original provider-wide configuration contract for
            # existing deployments and direct broker callers that do not yet
            # provide an approved permission set.
            return list(dict.fromkeys(self.scopes))
        selected: list[str] = []
        for permission in sorted(approved_permissions):
            selected.extend(self.scope_by_permission.get(permission, []))
        if not selected:
            raise OAuthError("OAuth provider scopes are not configured for approved permissions")
        return list(dict.fromkeys(selected))


class OAuthAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    authorization_url: str
    state: str
    expires_at: datetime


class OAuthCompletion:
    def __init__(
        self,
        *,
        user_id: str,
        plugin_id: str,
        credential: Mapping[str, str],
        approved_permissions: frozenset[str],
        account_label: str | None,
    ) -> None:
        self.user_id = user_id
        self.plugin_id = plugin_id
        self.credential = dict(credential)
        self.approved_permissions = approved_permissions
        self.account_label = account_label


class OAuthTransport(Protocol):
    def exchange_code(
        self,
        config: OAuthProviderConfig,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> Mapping[str, str]: ...


class HttpOAuthTransport:
    """Small provider-neutral token exchange client.

    Provider-specific authorization semantics remain in the registry config;
    this transport only handles the standard token exchange boundary.
    """

    def exchange_code(
        self,
        config: OAuthProviderConfig,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> Mapping[str, str]:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": config.client_id,
            "code_verifier": code_verifier,
        }
        if config.client_secret:
            data["client_secret"] = config.client_secret
        try:
            response = httpx.post(config.token_endpoint, data=data, timeout=15.0)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OAuthError("OAuth token exchange failed") from exc
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise OAuthError("OAuth token response did not include an access token")
        return {
            key: str(value)
            for key, value in payload.items()
            if isinstance(value, (str, int, float, bool))
        }


class _OAuthSession:
    def __init__(
        self,
        *,
        user_id: str,
        plugin_id: str,
        config: OAuthProviderConfig,
        redirect_uri: str,
        verifier: str,
        expires_at: datetime,
        approved_permissions: frozenset[str],
        account_label: str | None,
    ) -> None:
        self.user_id = user_id
        self.plugin_id = plugin_id
        self.config = config
        self.redirect_uri = redirect_uri
        self.verifier = verifier
        self.expires_at = expires_at
        self.approved_permissions = approved_permissions
        self.account_label = account_label


class _OAuthTerminal:
    def __init__(self, *, user_id: str, plugin_id: str, state: str, result: str, error: str | None = None) -> None:
        self.user_id = user_id
        self.plugin_id = plugin_id
        self.state = state
        self.result = result
        self.error = error


class OAuthBroker:
    def __init__(
        self,
        transport: OAuthTransport,
        *,
        ttl_seconds: int = 600,
        clock=None,
    ) -> None:
        if ttl_seconds <= 0:
            self._ttl = timedelta(seconds=ttl_seconds)
        else:
            self._ttl = timedelta(seconds=ttl_seconds)
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sessions: dict[str, _OAuthSession] = {}
        self._terminal: dict[str, _OAuthTerminal] = {}

    def start(
        self,
        *,
        user_id: str,
        plugin_id: str,
        config: OAuthProviderConfig,
        redirect_uri: str,
        approved_permissions: set[str] | frozenset[str] = frozenset(),
        account_label: str | None = None,
    ) -> OAuthAuthorizationRequest:
        provider_scopes = config.scopes_for_permissions(approved_permissions)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = _pkce_challenge(verifier)
        expires_at = self._clock() + self._ttl
        self._sessions[state] = _OAuthSession(
            user_id=user_id,
            plugin_id=plugin_id,
            config=config,
            redirect_uri=redirect_uri,
            verifier=verifier,
            expires_at=expires_at,
            approved_permissions=frozenset(approved_permissions),
            account_label=account_label,
        )
        query = urlencode({
            **config.authorization_params,
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(provider_scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        separator = "&" if "?" in config.authorization_endpoint else "?"
        return OAuthAuthorizationRequest(
            authorization_url=f"{config.authorization_endpoint}{separator}{query}",
            state=state,
            expires_at=expires_at,
        )

    def status(self, state: str, *, plugin_id: str) -> dict[str, str | None]:
        terminal = self._terminal.get(state)
        if terminal is not None and terminal.plugin_id == plugin_id:
            return {"pluginId": plugin_id, "state": terminal.result, "error": terminal.error}
        session = self._sessions.get(state)
        if session is not None and session.plugin_id == plugin_id:
            if session.expires_at <= self._clock():
                self._sessions.pop(state, None)
                self._terminal[state] = _OAuthTerminal(
                    user_id=session.user_id, plugin_id=plugin_id, state=state,
                    result="expired", error="oauth_expired"
                )
                return {"pluginId": plugin_id, "state": "expired", "error": "oauth_expired"}
            return {"pluginId": plugin_id, "state": "pending", "error": None}
        return {"pluginId": plugin_id, "state": "unknown", "error": None}

    def mark_failed(self, state: str, plugin_id: str, error: str = "oauth_connection_failed") -> None:
        user_id = self._owner(state, plugin_id) or "local-user"
        self._terminal[state] = _OAuthTerminal(
            user_id=user_id, plugin_id=plugin_id, state=state, result="failed", error=error
        )

    def owner(self, state: str, *, plugin_id: str) -> str | None:
        return self._owner(state, plugin_id)

    def _owner(self, state: str, plugin_id: str) -> str | None:
        session = self._sessions.get(state)
        if session is not None and session.plugin_id == plugin_id:
            return session.user_id
        terminal = self._terminal.get(state)
        if terminal is not None and terminal.plugin_id == plugin_id:
            return terminal.user_id
        return None

    def complete(
        self,
        *,
        user_id: str | None,
        plugin_id: str,
        state: str,
        code: str | None,
        error: str | None = None,
    ) -> OAuthCompletion:
        session = self._sessions.get(state)
        if session is None or (user_id is not None and session.user_id != user_id) or session.plugin_id != plugin_id:
            raise OAuthStateMismatch("OAuth state is invalid")
        self._sessions.pop(state, None)
        if session.expires_at <= self._clock():
            self._terminal[state] = _OAuthTerminal(
                user_id=session.user_id, plugin_id=plugin_id, state=state, result="expired", error="oauth_expired"
            )
            raise OAuthStateMismatch("OAuth state has expired")
        if error == "access_denied":
            self._terminal[state] = _OAuthTerminal(
                user_id=session.user_id, plugin_id=plugin_id, state=state, result="cancelled", error="oauth_cancelled"
            )
            raise OAuthCancelled("OAuth authorization was cancelled")
        if error:
            self._terminal[state] = _OAuthTerminal(
                user_id=session.user_id, plugin_id=plugin_id, state=state, result="failed", error="oauth_provider_error"
            )
            raise OAuthError(f"OAuth provider returned {error}")
        if not code:
            self._terminal[state] = _OAuthTerminal(
                user_id=session.user_id, plugin_id=plugin_id, state=state, result="failed", error="oauth_code_missing"
            )
            raise OAuthError("OAuth callback did not include an authorization code")
        try:
            credential = self._transport.exchange_code(
                session.config,
                code=code,
                code_verifier=session.verifier,
                redirect_uri=session.redirect_uri,
            )
        except Exception as exc:
            self._terminal[state] = _OAuthTerminal(
                user_id=session.user_id, plugin_id=plugin_id, state=state, result="failed", error="oauth_token_exchange_failed"
            )
            if isinstance(exc, OAuthError):
                raise
            raise OAuthError("OAuth token exchange failed") from exc
        self._terminal[state] = _OAuthTerminal(
            user_id=session.user_id, plugin_id=plugin_id, state=state, result="completed"
        )
        return OAuthCompletion(
            user_id=session.user_id,
            plugin_id=session.plugin_id,
            credential=credential,
            approved_permissions=session.approved_permissions,
            account_label=session.account_label,
        )


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
