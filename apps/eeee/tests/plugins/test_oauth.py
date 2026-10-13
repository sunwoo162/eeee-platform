from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.plugins.oauth import (
    OAuthBroker,
    OAuthCancelled,
    OAuthProviderConfig,
    OAuthStateMismatch,
)


class FakeOAuthTransport:
    def __init__(self):
        self.calls = []

    def exchange_code(self, config, *, code, code_verifier, redirect_uri):
        self.calls.append((config, code, code_verifier, redirect_uri))
        return {"access_token": "secret-token", "refresh_token": "secret-refresh"}


def _config() -> OAuthProviderConfig:
    return OAuthProviderConfig(
        authorizationEndpoint="https://provider.example/authorize",
        tokenEndpoint="https://provider.example/token",
        clientId="public-client",
        scopes=["mail.read", "mail.send"],
    )


def test_start_builds_pkce_authorization_url_without_exposing_verifier() -> None:
    broker = OAuthBroker(FakeOAuthTransport(), ttl_seconds=300)

    result = broker.start(
        user_id="user-a", plugin_id="gmail", config=_config(),
        redirect_uri="http://127.0.0.1:49152/oauth/callback",
        approved_permissions={"mail.read"}, account_label="Work",
    )

    query = parse_qs(urlparse(result.authorization_url).query)
    assert query["client_id"] == ["public-client"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"]
    assert "code_verifier" not in result.authorization_url
    assert result.expires_at > datetime.now(timezone.utc)


def test_complete_exchanges_code_and_consumes_one_time_session() -> None:
    transport = FakeOAuthTransport()
    broker = OAuthBroker(transport, ttl_seconds=300)
    request = broker.start(
        user_id="user-a", plugin_id="gmail", config=_config(),
        redirect_uri="http://127.0.0.1:49152/oauth/callback",
        approved_permissions={"mail.read"}, account_label="Work",
    )
    state = parse_qs(urlparse(request.authorization_url).query)["state"][0]

    credential = broker.complete(
        user_id="user-a", plugin_id="gmail", state=state, code="auth-code"
    )

    assert credential.credential == {"access_token": "secret-token", "refresh_token": "secret-refresh"}
    assert credential.approved_permissions == frozenset({"mail.read"})
    assert credential.account_label == "Work"
    assert transport.calls[0][1] == "auth-code"
    with pytest.raises(OAuthStateMismatch):
        broker.complete(user_id="user-a", plugin_id="gmail", state=state, code="again")


def test_complete_rejects_cross_user_and_expired_sessions() -> None:
    broker = OAuthBroker(FakeOAuthTransport(), ttl_seconds=300)
    request = broker.start(
        user_id="user-a", plugin_id="gmail", config=_config(),
        redirect_uri="http://127.0.0.1:49152/oauth/callback",
    )
    state = parse_qs(urlparse(request.authorization_url).query)["state"][0]

    with pytest.raises(OAuthStateMismatch):
        broker.complete(user_id="user-b", plugin_id="gmail", state=state, code="code")

    expired = OAuthBroker(FakeOAuthTransport(), ttl_seconds=-1)
    request = expired.start(
        user_id="user-a", plugin_id="gmail", config=_config(),
        redirect_uri="http://127.0.0.1:49152/oauth/callback",
    )
    state = parse_qs(urlparse(request.authorization_url).query)["state"][0]
    with pytest.raises(OAuthStateMismatch):
        expired.complete(user_id="user-a", plugin_id="gmail", state=state, code="code")


def test_cancel_does_not_exchange_or_leak_a_credential() -> None:
    transport = FakeOAuthTransport()
    broker = OAuthBroker(transport, ttl_seconds=300)
    request = broker.start(
        user_id="user-a", plugin_id="gmail", config=_config(),
        redirect_uri="http://127.0.0.1:49152/oauth/callback",
    )
    state = parse_qs(urlparse(request.authorization_url).query)["state"][0]

    with pytest.raises(OAuthCancelled):
        broker.complete(
            user_id="user-a", plugin_id="gmail", state=state,
            code=None, error="access_denied",
        )
    assert transport.calls == []
