from app.plugins.oauth import OAuthProviderConfig
from app.plugins.providers import (
    INITIAL_PROVIDER_IDS,
    ProviderConfig,
    build_provider_connectors,
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
    assert connectors["gmail"].health_path == "/profile"


def test_provider_configs_load_from_json_without_accepting_secrets_in_catalog() -> None:
    configs = load_provider_configs(
        '{"gmail": {"baseUrl": "https://gmail.example", "oauth": {'
        '"authorizationEndpoint": "https://accounts.example/authorize", '
        '"tokenEndpoint": "https://accounts.example/token", '
        '"clientId": "public-client", "scopes": ["mail.read"]}}}'
    )

    assert configs["gmail"].oauth.client_id == "public-client"
    assert configs["gmail"].oauth.client_secret is None
