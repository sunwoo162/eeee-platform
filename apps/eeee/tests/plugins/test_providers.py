from app.plugins.oauth import OAuthProviderConfig
from app.plugins.providers import (
    INITIAL_PROVIDER_IDS,
    ProviderConfig,
    _refresh_oauth_credential,
    build_provider_connectors,
    build_gmail_provider_config,
    load_provider_configs,
)


def _oauth() -> OAuthProviderConfig:
    return OAuthProviderConfig(
        authorizationEndpoint="https://accounts.example/authorize",
        tokenEndpoint="https://accounts.example/token",
        clientId="public-client",
        scopes=["read"],
    )


def test_initial_provider_specs_cover_the_catalog_candidates() -> None:
    assert {
        "gmail", "google-calendar", "google-drive", "google-contacts",
        "github", "figma", "slack", "linear", "todoist",
        "outlook-email", "outlook-calendar",
    }.issubset(INITIAL_PROVIDER_IDS)


def test_provider_factory_only_builds_explicitly_configured_connectors() -> None:
    connectors = build_provider_connectors({
        "gmail": ProviderConfig(
            baseUrl="https://gmail.example",
            oauth=_oauth(),
        )
    })

    assert set(connectors) == {"gmail"}
    assert connectors["gmail"].plugin_id == "gmail"
    assert connectors["gmail"].health_path == "/users/me/profile"


def test_provider_configs_load_from_json_without_accepting_secrets_in_catalog() -> None:
    configs = load_provider_configs(
        '{"gmail": {"baseUrl": "https://gmail.example", "oauth": {'
        '"authorizationEndpoint": "https://accounts.example/authorize", '
        '"tokenEndpoint": "https://accounts.example/token", '
        '"clientId": "public-client", "scopes": ["mail.read"]}}}'
    )

    assert configs["gmail"].oauth.client_id == "public-client"
    assert configs["gmail"].oauth.client_secret is None


def test_gmail_provider_profile_uses_internal_client_settings() -> None:
    config = build_gmail_provider_config("gmail-client", "gmail-secret")

    assert config.base_url == "https://gmail.googleapis.com/gmail/v1"
    assert config.health_path == "/users/me/profile"
    assert config.oauth.authorization_endpoint == "https://accounts.google.com/o/oauth2/v2/auth"
    assert config.oauth.token_endpoint == "https://oauth2.googleapis.com/token"
    assert config.oauth.scope_by_permission["mail.read"] == [
        "https://www.googleapis.com/auth/gmail.readonly"
    ]
    assert config.oauth.authorization_params["access_type"] == "offline"


def test_gmail_provider_profile_is_loaded_without_user_facing_json() -> None:
    configs = load_provider_configs(
        None,
        gmail_client_id="gmail-client",
        gmail_client_secret="gmail-secret",
    )

    assert set(configs) == {"gmail"}
    assert configs["gmail"].oauth.client_id == "gmail-client"


def test_oauth_credential_refresh_keeps_refresh_token_and_updates_access_token(monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"access_token": "new-access", "expires_in": 3600}

    calls = []
    monkeypatch.setattr(
        "app.plugins.providers.httpx.post",
        lambda url, *, data, timeout: calls.append((url, data, timeout)) or Response(),
    )
    config = build_gmail_provider_config("gmail-client", "gmail-secret").oauth

    refreshed = _refresh_oauth_credential(
        {"access_token": "old-access", "refresh_token": "refresh"}, config
    )

    assert refreshed["access_token"] == "new-access"
    assert refreshed["refresh_token"] == "refresh"
    assert calls[0][0] == config.token_endpoint
    assert calls[0][1]["grant_type"] == "refresh_token"
