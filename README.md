# Gleave

For development continuity across ChatGPT/Codex conversations, read [`AGENTS.md`](AGENTS.md) and [`docs/DEVELOPMENT_HANDOFF.md`](docs/DEVELOPMENT_HANDOFF.md), then run `pwsh -NoProfile -File scripts/gleave-context.ps1` in the local checkout before editing. The script is read-only and reports live Git state.

`Gleave` is one local-first open-source personal assistant platform combining:

- EEEE: the top-level assistant that understands context and chooses the best capability or connector.
- ISEOL: the project-execution capability that owns Agent organization, task decomposition, execution, integration, QA, and evaluation when the request is a project.
- ClaimLatch: the global evidence-backed reliability gate for assistant claims, actions, Agent reports, release reports, and memory candidates.

The user operates one Gleave application through EEEE. Project creation produces one unified Project Runtime that binds local workspace, ISEOL, Notion documentation, Calendar, GitHub CI/code review, Desktop local hosting, Mobile remote control, QA baselines, and project memory under one `projectId`. The platform runs on a local computer without a hosted login or central EEEE server; external services are optional adapters around the local core.

## Repository layout

~~~text
apps/eeee                 Python EEEE assistant kernel and local application
packages/iseol            TypeScript ISEOL project-execution runtime
packages/claimlatch       Bundled ClaimLatch verification engine
integrations/contracts    Versioned cross-runtime contracts
integrations/claimlatch   Local ClaimLatch adapter
docs                      Canonical architecture, plans, and operations
scripts                   Local repository and verification scripts
~~~

## Core assistant and trust flow

~~~text
User request
  -> EEEE context, memory, and capability selection
  -> Personal Secretary / Project Runtime / Documents / Presence
  -> ISEOL Agent teams when project execution is selected
  -> independent QA and deterministic evidence
  -> ClaimLatch action/report verification
  -> Release Gate for one current project revision
  -> EEEE persistent memory candidate
  -> approved/scoped memory used by the next request
~~~

Code behavior is verified deterministically. Natural-language claims, external actions, Agent reports, and release reports are verified through ClaimLatch. A verification failure never becomes a trusted side effect, release, or active memory rule.

The platform integration profile is `claimlatch-v0.2.0`. The audit preserves the actual bundled engine version separately from the profile version.

ClaimLatch text verification returns the versioned `VerificationEnvelopeV1`. EEEE stores the request payload hash, report ID, optional receipt ID, policy version, adapter version, ClaimLatch version, project revision, and full envelope in the same local SQLite database as project state and memory. Replaying one subject at the same revision with a different payload or policy metadata is rejected; a stale revision is rejected before the adapter is called when a current-revision resolver is configured.

ISEOL QA is an independent release gate, not an Agent completion message. `QaPlan` creates QA-0 through QA-5 checks, `QaOrchestrator` requires executable command evidence, `EvidenceLedger` records exit status and stdout/stderr hashes, and `ReleaseGate` requires matching current revisions across QA, deterministic verification, and ClaimLatch before release.

## Source repositories

The imported source revisions and exclusions are recorded in repository-manifest.json. The original source folders remain preserved outside this aggregate repository.

## Current status

The first local vertical slice is implemented. The verified core path includes:

1. ClaimLatch local Adapter with versioned envelopes and durable audit records.
2. EEEE persistent memory storage, retrieval, promotion, and stale-outcome rejection.
3. ISEOL independent QA planning, executable evidence ledger, stale-revision checks, and release gate.
4. Durable assistant jobs that survive UI restart, with pause, resume, retry, and cancel controls.
5. Safe memory inspection/deletion with audit events and a desktop/web control-center snapshot.
6. Release artifact path, revision, UTF-8, evidence, and ClaimLatch gate checks.

This status refers to the local core only. Optional external plugins, hosted providers, and the
full ISEOL Agent organization runtime are separate integration scopes and are not silently treated
as complete.

The approved redesign adds the extensible EEEE capability registry and unified Project Runtime foundation. See [`docs/architecture/eeee-platform.md`](docs/architecture/eeee-platform.md) for the target boundary and [`docs/superpowers/plans/2026-10-06-eeee-personal-assistant-platform-plan.md`](docs/superpowers/plans/2026-10-06-eeee-personal-assistant-platform-plan.md) for the implementation sequence.

The desktop companion is an always-on-top PySide6 launcher with tray hide/restore/quit behavior. It keeps the quick EEEE assistant, ClaimLatch/mobile status, and language choice visible without duplicating the full product UI. The existing local browser workbench is opened from the companion and remains the primary project surface. EEEE owns the local API, approvals, project memory, and user-facing state; ISEOL owns Agent decomposition, Workstream/team composition, execution, handoffs, integration, QA, and evaluation.

ISEOL is used as the internal project-execution Harness Coordinator. Its required project surface is GitHub CI/code review plus Notion documentation; Discord is not provisioned by the core runtime. Desktop owns execution and Mobile forwards commands/status through a paired bridge. A review result is never treated as a release approval by itself: deterministic QA and ClaimLatch must still agree on the same project revision.

## Local setup

Requirements: Python 3.12+, Node.js 20+, npm, and Windows PowerShell for the helper scripts.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\eeee[dev,desktop]"
Push-Location .\packages\iseol; npm ci; Pop-Location
Push-Location .\packages\claimlatch; npm ci; Pop-Location
Push-Location .\integrations\claimlatch-adapter; npm ci; Pop-Location
```

Start the local EEEE API and widget:

```powershell
.\scripts\dev-up.ps1
Push-Location .\apps\eeee
..\..\.venv\Scripts\python.exe -m app.desktop
Pop-Location
```

Run the focused unified verification, or the full EEEE suite:

```powershell
.\scripts\verify-all.ps1
.\scripts\verify-all.ps1 -Full
```

For the core product acceptance gate on Windows, run:

```powershell
.\scripts\verify-core-product.ps1
```

The `scripts/verify-core-product.ps1` command runs the durable job, memory, desktop control-center, release-manifest, and core
project-flow tests, checks tracked text files as strict UTF-8, and fails on `git diff --check`.
It is the minimum evidence required before calling the local core release-ready.

No hosted login or central server is required. Optional Notion, mobile, calendar, and future channel adapters connect to the local core. Never commit `.env`, credentials, runtime databases, `node_modules`, virtual environments, `dist`, or `__pycache__`.

ClaimLatch is installed as the official default plugin. Put its provider settings in
`apps/eeee/.env`; when both `CLAIMLATCH_LLM_MODEL` and `TAVILY_API_KEY` are present,
EEEEs starts the bundled loopback adapter automatically and shuts it down with the
application. Users do not need to start a second terminal process. Without those
credentials, EEEE remains usable but release and memory promotion stay blocked.

## One-sentence project flow

Open the local Gleave page, leave the language as Korean or select English, and enter a single request such as `Todo 앱 만들어줘` (or `Build a Todo app`). EEEE creates the local Project Runtime and opens its project map automatically. The map is the user-facing organization view: active and completed tasks, current commits, changed files, ClaimLatch status, independent QA, evidence, troubleshooting references, and retry/block states are shown from durable records rather than inferred UI text.

The older request/research/approval panels remain available below the assistant launcher for detailed control. The default project workspace is the configured local workspace root; users can change it later through the existing request controls.

Plugins are separate local tools, not bundled into the core. Ask EEEE to connect a plugin or use `/api/plugins`: inspect its manifest and permissions, approve it, run its local health check, then invoke it through the versioned JSON protocol. Plugin actions are isolated subprocesses and return the same `ExecutionEnvelope` used by the core. No login or hosted plugin registry is required.

## Upstream attribution

The aggregate preserves the source projects as separate imported components. Their original repositories, licenses, remotes, branches, commits, and excluded runtime files are recorded in [`repository-manifest.json`](repository-manifest.json). The source folders remain preserved outside this checkout as upstream references.

