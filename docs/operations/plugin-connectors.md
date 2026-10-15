# EEEE optional plugin connectors

EEEE ships the plugin catalog and the install/connect UI, but provider accounts
are intentionally not preinstalled or shared. A distribution enables a provider
only when its public API base URL and OAuth client configuration are supplied by
the operator.

## Configuration

Set `PLUGIN_PROVIDER_CONFIG_JSON` (or the equivalent `plugin_provider_config_json`
field in `Settings`) to a JSON object keyed by catalog plugin id. The value
contains the provider API base URL and an OAuth Authorization Code + PKCE
configuration:

```json
{
  "gmail": {
    "baseUrl": "https://provider.example/api",
    "healthPath": "/profile",
    "oauth": {
      "authorizationEndpoint": "https://provider.example/oauth/authorize",
      "tokenEndpoint": "https://provider.example/oauth/token",
      "clientId": "public-client-id",
      "scopes": ["mail.read", "mail.send"],
      "scopeByPermission": {
        "mail.read": ["provider.read"],
        "mail.send": ["provider.send"]
      }
    }
  }
}
```

The catalog remains visible when a provider is not configured, but its state is
`disabled` and it cannot be installed or routed. This prevents a UI entry from
pretending that an external integration is usable. Client secrets are not
stored in the catalog; use an operator secret mechanism for providers that
require one and keep it out of source control.

## User flow

1. The user selects **Install** in EEEE's plugin control center.
2. EEEE opens the provider's OAuth page in the user's browser. The desktop
   client selects the default read-only EEEE permissions automatically, and
   `scopeByPermission` limits the provider scopes to those approved actions.
   Write permissions remain opt-in.
3. The local callback verifies state and PKCE, exchanges the code, health-checks
   the provider, and stores the resulting credential in the OS credential
   store.
4. EEEE exposes only the connected provider's approved capabilities to routing.
   Read capabilities do not require an external-write approval; send/create/
   update operations are marked external and require approval.

Existing ChatGPT/Codex connectors are not copied into EEEE. Each connector must
have a public provider contract, a user-scoped OAuth/API boundary, and tests
against the provider-neutral connector interface before it is marked usable.
