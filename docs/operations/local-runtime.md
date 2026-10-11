# Local runtime

EEEE is the local entrypoint. It starts a FastAPI coordinator bound to `127.0.0.1`, stores project state, ClaimLatch verification audits, and durable memory in one SQLite database, and can launch the PySide6 desktop companion without a login or hosted control plane.

From the repository root:

```powershell
python -m pip install -e ".\apps\eeee[desktop,desktop-build]"
.\scripts\dev-up.ps1
# Or launch the local API and PySide6 EEEE widget together:
.\scripts\desktop-up.ps1
# To build a local Windows executable:
.\scripts\build-desktop.ps1
# After building, verify the packaged runtime without opening the window:
build\desktop\GleaveDesktop.exe --self-test
```

The widget is always-on-top, draggable, interactive, and can hide to or restore from the system tray. It talks only to the local EEEE API. Notion, Google Calendar, and GitHub CI/code review are optional provider adapters; ISEOL runs locally and Discord is not a required runtime dependency.

## EEEE general conversation engine

EEEE uses the ISEOL ChatGPT Web bridge for general conversation when
`CHATGPT_WEB_ENABLED=true` and `CHATGPT_WEB_BRIDGE_URL` points to the loopback
bridge. The bridge owns a dedicated persistent browser profile and the user
logs into ChatGPT Web once in that profile; EEEE never receives the profile's
cookies, passwords, or tokens. The browser adapter checks authentication,
conversation identity, response extraction, and ChatGPT usage-limit states.

This is browser-session usage, not an OpenAI API integration: it does not add
API token billing, but it still consumes the user's ChatGPT plan allowance and
can be blocked by that plan's limits. If the bridge is enabled but unavailable,
EEEE returns a blocked connection state instead of pretending that a fixed
fallback response came from GPT. When the bridge is disabled, the local
deterministic fallback is only a development mode and is not a live GPT
conversation.

For automatic local startup, set `CHATGPT_WEB_ENABLED=true`,
`CHATGPT_WEB_AUTOSTART=true`, and choose a dedicated profile directory in
`CHATGPT_WEB_PROFILE_ROOT`. Set `CHATGPT_WEB_HEADLESS=false` for the first run;
the opened ChatGPT Web window is where the user completes the normal login.
After login, the same profile is reused on later launches. The profile must be
dedicated to Gleave and must not be the user's active everyday Chrome profile.

Desktop's companion exposes the quick EEEE command input and opens the existing
browser workbench as the primary project surface. The browser UI calls
`POST /api/assistant/route`; after a project is created, Desktop refreshes
`GET /api/desktop/state?projectId=...` and shows the Project Runtime state,
ClaimLatch profile/health, and redacted lifecycle events. The local event journal
is available to the shell through `GET /api/desktop/events`. Pairing starts only
from the loopback-only `POST /api/desktop/pairing/code` route and returns a
short-lived code without returning a Mobile access token.

The shortest project path is the assistant launcher in the browser workbench:

```text
Todo 앱 만들어줘
  -> POST /api/assistant/route
  -> projectId
  -> GET /api/projects/{projectId}/map
```

The map polls the durable event cursor without replacing the page. Selecting a
node shows its role, status, current commit, changed files, ClaimLatch receipt
status, independent QA status, evidence IDs, and troubleshooting references.
Korean is the default UI language; the language selector switches the launcher
and existing workbench labels to English.

Local plugin tools are intentionally outside the body. A plugin manifest is
discovered and registered through `/api/plugins/discover` and
`/api/plugins/{pluginId}/register`, then EEEE requires explicit permission
approval before `/connect` runs a health check. `/invoke` starts a bounded,
correlated JSON subprocess and returns an `ExecutionEnvelope`; failed startup,
protocol mismatch, timeout, or denied permissions never become a completed
action. The host stores manifest and lifecycle audit state only, so installing a
plugin does not import its code into EEEE.

Desktop is the authoritative runtime. Mobile is distributed separately as a thin
remote client: it pairs with a short-lived code, sends commands through the Desktop
bridge, and subscribes to `GET /api/mobile/events/stream` for live state. Existing
secretary features remain available on Mobile because the command is executed by
EEEE on Desktop. Mobile never receives provider tokens or the local SQLite database.

For a project request, EEEE creates one durable Project Runtime and automatically
attempts the revision-bound Notion project document sync when that connector is
configured. GitHub receives repository, CI, and code-review integration when
configured. ISEOL owns Agent decomposition, integration, and independent QA locally.
A missing provider stays
`awaiting_configuration` and is never reported as completed.

When `NOTION_TOKEN` and `NOTION_PARENT_PAGE_ID` are configured, use
`POST /api/projects/{projectId}/documents/sync` to create or append the
revision-bound project document. The Notion write is ClaimLatch-gated and the
page reference is stored in the same SQLite database. `POST
/api/projects/{projectId}/evidence/github-review` is the local ISEOL evidence
boundary; it rejects stale revisions and emits a redacted Desktop event.

ISEOL can deliver GitHub CI/code-review evidence without Discord through
`npm run review:standalone` in `packages/iseol`. Set `GITHUB_TOKEN`,
`EEEE_BRIDGE_URL`, and the per-project `eeeeProjectId`/`eeeeProjectRevision`
mapping. The worker uses the exact PR HEAD SHA, posts the GitHub review, and
delivers the versioned evidence contract to EEEE. Discord remains legacy and
optional for this path.

The ClaimLatch integration profile is `claimlatch-v0.2.0`. Audit records preserve that
profile separately from the bundled engine version (`0.3.86`), and `/health` exposes only
non-secret status metadata (`configured`, `advisory`, or `required`).

ClaimLatch is shipped as Gleave's default official plugin. Configure
`CLAIMLATCH_LLM_MODEL`, optional `CLAIMLATCH_LLM_API_KEY`/`CLAIMLATCH_LLM_BASE_URL`, and
`TAVILY_API_KEY` in `apps/eeee/.env`. EEEE automatically starts the local adapter on
`127.0.0.1:4318` and owns its lifecycle; `CLAIM_LATCH_ADAPTER_URL` is only needed when
connecting to an externally managed adapter. Missing provider credentials do not stop
Gleave, but they leave the trust gate advisory and prevent release or memory promotion.

For a ClaimLatch client that must be trusted by EEEE, pass the coordinator's `SQLiteStore.claimlatch_audits` to `ClaimLatchClient`, configure the current project revision resolver, and keep the client fail-closed. The audit row is written only after the adapter returns a schema-valid envelope whose subject, project, and revision match the request.

Run the focused local verification:

```powershell
.\scripts\verify-all.ps1
```

Use `-Full` for the complete EEEE Python suite. The ClaimLatch adapter is a loopback/process boundary and must remain fail-closed: a transport error, malformed report, missing evidence, stale revision, replay conflict, or blocked ClaimLatch decision cannot become a released answer or memory candidate.
