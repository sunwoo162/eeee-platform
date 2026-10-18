# Gleave

Gleave is a local-first FastAPI workbench and personal assistant platform. EEEE routes user intent, ISEOL executes project work, and ClaimLatch verifies claims and actions before release or memory promotion. The browser UI is served by the local process and uses no third-party CDN assets.

This repository is released under the MIT License and is intended for
self-hosted use. It is not a hosted multi-tenant service.

## Native EEEE → ISEOL project flow

EEEE accepts a one-sentence project request and keeps the local execution
contract deterministic:

```text
POST /api/assistant/route
  → background project identity
  → native ISEOL intent and specialist graph
  → template-specific local scaffold
  → API/static QA and ClaimLatch release gate
  → FINAL-QUALITY-REPORT.json
```

For example, `오늘 식단을 정리해주는 웹 만들어줘` selects the native
`meal_planner` template. The project view exposes only safe progress metadata:
`GET /api/projects/{project_id}/execution-plan` omits the raw request,
credentials, and agent system prompts; `GET /api/projects/{project_id}/quality`
returns `awaiting` until the evidence-backed final report exists.

The current native lane is intentionally local-first and provider-neutral.
Browser UI E2E is reported as `NOT_RUN` when a browser engine is not configured,
so a local/API-verified project may be `client_ready_with_notes` rather than
silently being called portfolio-complete. A failed specialist, missing QA, bad
encoding, missing rollback evidence, or ClaimLatch failure produces a blocked
final report.

Plugin implementations are not included in this phase. The graph can record
selected or missing extension manifests, but it does not pretend that Gmail,
GitHub, Figma, Notion, or other external actions happened. Those actions stay
pending until the corresponding connector is installed, explicitly approved,
and independently verified.

The full native flow and its evidence contract are documented in
[docs/ISEOL_NATURAL_LANGUAGE_FLOW.md](docs/ISEOL_NATURAL_LANGUAGE_FLOW.md).

## Windows setup

From PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Start the service:

```powershell
python -m app.main
```

After installation, the equivalent console command is:

```powershell
gleave
```

Open <http://127.0.0.1:8000/>. The health endpoint is <http://127.0.0.1:8000/health>.

For a containerized demo:

```powershell
docker compose up --build
```

Then open <http://127.0.0.1:8000/>. Docker uses demo mode and persists SQLite
state and workspaces in named volumes.

## Development

Install contributor dependencies and run the full suite:

```powershell
python -m pip install -e ".[dev]"
$env:QT_QPA_PLATFORM="offscreen"
python -m pytest -q
```

Build and inspect release artifacts with `python -m build --no-isolation` and
`python scripts/check_artifacts.py dist`. See [CONTRIBUTING.md](CONTRIBUTING.md)
and [docs/RELEASE.md](docs/RELEASE.md) for contributor and maintainer flows.

## Configuration

Copy `.env.example` to `.env` when environment configuration is needed.

| Variable | Purpose | Default |
| --- | --- | --- |
| `APP_NAME` | FastAPI application title | `Gleave` |
| `DATA_DIR` | SQLite state directory | `.gleave` |
| `WORKSPACE_ROOT` | Allowed root for request workspaces | `workspaces` |
| `GITHUB_TOKEN` | Optional GitHub API token for live research | empty |
| `LLM_BASE_URL` | Optional OpenHands-compatible model endpoint | empty |
| `LLM_API_KEY` | Optional model API key | empty |
| `LLM_MODEL` | Optional model identifier | empty |
| `EXECUTION_MODE` | `demo` or deterministic `workspace_verify` | `demo` |
| `COMMAND_TIMEOUT_SECONDS` | Maximum duration of a verification command | `120` |
| `MAX_COMMAND_OUTPUT_CHARS` | Output limit recorded per command | `8000` |
| `EEEE_CONVERSATION_PROVIDER` | General conversation provider: `chatgpt_web` by default; `ollama` is an explicit migration/debug override | `chatgpt_web` |
| `EEEE_OLLAMA_BASE_URL` | Ollama endpoint for local conversation generation | `http://127.0.0.1:11434` |
| `EEEE_OLLAMA_MODEL` | Ollama model used by the local provider | empty |
| `CHATGPT_WEB_ENABLED` | Enables the optional ChatGPT Web bridge | `false` |
| `CHATGPT_WEB_BRIDGE_URL` | Local bridge URL used by the Web GPT adapter | `http://127.0.0.1:47831` |

OpenHands is optional. Research, comparison, approval, and the UI remain available without `LLM_API_KEY` or `LLM_MODEL`; an execution run is recorded as `unavailable` with a configuration error until those values and a compatible OpenHands SDK are installed.

To enable the real ISEOL coding-agent runtime in the same virtual environment,
install the pinned SDK/tool pair and configure an OpenHands-compatible model:

```powershell
python -m pip install -e ".[agent,desktop,dev]"
$env:LLM_MODEL = "your-provider/model-name"
$env:LLM_API_KEY = "your-model-provider-key"
# Optional for an OpenAI-compatible endpoint:
# $env:LLM_BASE_URL = "https://your-provider.example/v1"
python -m app.desktop
```

The application does not accept a browser ChatGPT login as an API credential.
The desktop shell must receive an explicit model endpoint/key, and it keeps the
run unavailable instead of claiming that an AI agent completed work when the
runtime is not configured. The pinned `openhands-sdk` and `openhands-tools`
versions are installed together because the distributions are released as a
matched pair.

Ollama is not part of the active EEEE assistant path. The legacy local-agent
path can still be enabled explicitly for migration/debugging by setting
`EEEE_CONVERSATION_PROVIDER=ollama`, but a missing Web GPT bridge never falls
back to it.

For that explicit legacy path, install Ollama separately, pull a local model,
and configure `EEEE_OLLAMA_MODEL` (or the equivalent `OLLAMA_MODEL` setting):

```powershell
ollama pull qwen2.5-coder:7b
$env:EEEE_CONVERSATION_PROVIDER = "ollama"
$env:EEEE_OLLAMA_MODEL = "qwen2.5-coder:7b"
python -m app.desktop
```

The local model proposes structured actions; EEEE remains responsible for
workspace boundaries, command execution, evidence, QA, and ClaimLatch gates.

### Conversation provider and growth memory

The general conversation path uses one provider contract. EEEE uses the
ChatGPT Web adapter as its active assistant brain. `chatgpt_web` is the default
and `auto` is retained only as a migration alias that also refuses to fall back
to Ollama. Set `ollama` only for an explicit local migration/debug run; normal
Web GPT failures remain visible instead of silently switching models.
`GET /v1/runtime` exposes the selected provider and readiness of both providers.

User feedback is stored separately from assistant memory. Submit a rating to
`POST /api/memory/feedback`; it is retained as a redacted feedback ledger entry
and does not change assistant behavior by itself. Include `remember: true` and
a non-empty `correction` only when the user explicitly wants the correction to
become an active, editable routing memory. Only active, non-expired memories
are bounded into later conversation context; raw conversation text and ordinary
positive/negative ratings are never promoted automatically.

## Approval model

The first execution always crosses an approval boundary:

1. Submit a request and choose a workspace inside `WORKSPACE_ROOT`.
2. Research and compare at least two OSS candidates, including evidence, license data, and risks.
3. Select the candidate(s) and approve the decision.
4. Execute the approved run through the injected runtime adapter.
5. Review the persisted event log, changed files, test commands, and workspace report bundle.

The API returns HTTP 409 if a run is executed before its decision is approved. Workspace paths outside the configured root are rejected before a run is created. The runtime prompt also disallows package installation, deletion, external transfer, and system-wide changes unless a future explicit policy grants them.

## API flow

```text
POST /api/requests
GET  /api/requests/{request_id}
POST /api/requests/{request_id}/research
POST /api/requests/{request_id}/approve
POST /api/runs/{run_id}/execute
POST /api/runs/{run_id}/retry
GET  /api/runs/{run_id}
GET  /api/runs?request_id={request_id}&status={status}&search={text}&created_after={iso}&created_before={iso}&sort={newest|oldest}&limit={limit}&offset={offset}
POST /api/design/references
GET  /api/design/references/{id}
POST /api/design/verify
POST /api/memory/feedback
```

The older `/projects/{project_id}/...` endpoints remain available for the desktop coordinator flow. The default application uses demo candidates when no GitHub token is configured; tests inject a fake researcher and runtime so they never need live credentials.

The browser stores the latest request ID locally and can restore its brief, candidates, approval, and latest run from `GET /api/requests/{request_id}` after a page reload or service restart. The snapshot also includes the approval audit events and a work plan derived from the persisted request and candidates. The restore control is local-only and does not transmit the ID outside the configured API.

The Recent runs panel browses runs across requests. It supports request/run ID search, status and local-time creation filters, newest/oldest ordering, 25/50/100 runs per page, manual refresh, and a Clear filters action. These run-history controls are stored in local browser storage, so a reload preserves the selected controls; the loaded page offset starts over at the first page. Clear filters removes the stored values and returns to newest-first with 50 runs per page. Paginated responses expose `X-Total-Count` and `X-Has-More` headers.

## Desktop coordinator

The existing desktop pet remains available when the optional desktop dependency is installed:

```powershell
python -m pip install -e ".[desktop,dev]"
python -m app.desktop
```

It starts the local API in-process. To point it at an already running API, set `PET_API_URL` and `PET_PROJECT_ID` before launching it:

```powershell
$env:PET_API_URL = "http://127.0.0.1:8000"
$env:PET_PROJECT_ID = "default"
python -m app.desktop
```

The desktop flow supports the same `demo` and explicit `workspace_verify` modes. In `workspace_verify`, only bounded compile, test, and git-diff checks run inside the approved workspace with `shell=False`; no install, delete, commit, push, or deployment command is performed automatically.

## Sample artifacts

Each API run writes evidence below `<workspace>/<run_id>/`:

- `OSS-DECISIONS.md`: selected repositories, URLs, licenses, branches, evidence, risks, and alternatives.
- `DEPENDENCIES.lock`: recorded source/branch pins and a note that packages were not installed automatically.
- `TEST-RESULTS.md`: reported test commands, run status, summary, and error state.
- `FINAL-REPORT.md`: final status, summary, changed files, and verification commands.

The SQLite store also records the structured run, ordered events, artifacts, and error state.

Design references preserve source URL, capture time, licence evidence, allowed uses, and attribution. Unknown licences are marked `reference_only`; the UI can extract derived tokens and layout patterns but has no site-copy action. Visual verification accepts local app URLs only and uses Playwright when that optional dependency and a browser are installed.

## Verification

Run the full suite from PowerShell:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
```

The redesign keeps deterministic tests separate from local-runtime checks:

```powershell
$env:PYTHONPATH = "."
python -m pytest tests -q
python scripts/benchmark_core.py
python scripts/smoke_restart_recovery.py
python scripts/smoke_ollama.py
```

`benchmark_core.py` measures a warm Core process. `smoke_restart_recovery.py`
must report an `interrupted` request after recovery. `smoke_ollama.py` returns
exit code `0` only when the configured Ollama endpoint and model are ready; a
missing server or model is reported as `blocked`/`unavailable`, never as a
completed assistant response. A local Ollama installation is not required for
the deterministic test suite.

Core dependencies do not include PySide6, Node, Playwright, ISEOL, or
OpenHands. PySide6 is only in the `desktop` extra, and optional project
runtimes are lazy-loaded when a project execution is actually selected.

The suite uses deterministic fakes for GitHub and agent execution. A warning from the installed Starlette/httpx compatibility layer may appear; it does not affect the test result.

On Windows, if pytest cannot create its default temporary directory, provide a writable basetemp explicitly:

```powershell
python -m pytest --basetemp .superpowers\pytest-tmp -q
```

For the desktop window smoke check, use `QT_QPA_PLATFORM=offscreen` so Qt does not require a visible display.

## Troubleshooting

- GitHub rate limits or malformed responses are reported as recoverable research errors. Set `GITHUB_TOKEN` for a higher authenticated limit, or use the deterministic demo mode.
- A `Runtime unavailable` result means the optional model configuration or OpenHands SDK is missing. Set `LLM_API_KEY`, `LLM_MODEL`, and optionally `LLM_BASE_URL`, then restart the service.
- A workspace rejection means the requested path is outside `WORKSPACE_ROOT`; choose a child directory instead.
- Verification commands are fixed, bounded, and run without a shell. A failed check is recorded in the report for retry rather than treated as a successful agent claim.

## Safety boundaries

- The agent runtime is given an approved workspace and an explicit action set.
- Candidate selection and implementation are separate from research and require explicit approval.
- External messaging, deployment, purchases, deletion, data transfer, and system-wide changes are outside the MVP.
- The coordinator records revisions and blocks stale verification results rather than silently applying them.
