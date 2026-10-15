# EEEE Core Redesign Design

## Status

Proposed architecture approved at the approach level by the user on 2026-10-15.
Implementation is intentionally not started by this document. The next gate is
review of this written specification, followed by a separate implementation
plan.

## Decision

Use approach 2: **EEEE Core + thin Desktop Shell + optional capabilities**.

EEEE Core is the small, always-available local personal-assistant service. It
owns conversations, local AI routing, memory, policy, durable state, and task
events. The Desktop Shell is only a presentation and input surface. Project
execution, ISEOL, ChatGPT Web, browser automation, external connectors, and
future plugins are optional capabilities loaded only when needed.

The user experiences one EEEE product, but the runtime is split by
responsibility. “Separate” means a capability can be installed, disabled, or
removed without rebuilding the core; it does not mean that every capability
starts another permanent AI server or database.

## 1. Current-state audit

This section records the repository as it actually exists. It is not a claim
that the current product is complete.

### 1.1 What exists

- `apps/eeee` contains a FastAPI application, SQLite-backed project state,
  memory lifecycle code, execution envelopes, trust gates, a plugin subprocess
  host, a mobile bridge, project provisioning, and a PySide6 desktop surface.
- `KernelService` records route executions and applies capability policy,
  approval state, project identity, revision checks, and trust decisions.
- Project requests can create a project, workspace, request, project profile,
  connector plan, run record, and project evidence boundary.
- Agent runtime adapters exist for OpenHands, ISEOL Project Runtime, and an
  ISEOL ChatGPT Web bridge.
- Project memory has candidate/active/superseded/revoked states and refuses
  promotion when deterministic QA, identity, or ClaimLatch evidence is
  missing.
- `PluginHost` can discover a manifest, register it, approve permissions,
  health-check a local process, invoke an action, disconnect it, and remove
  the registration.
- Desktop can start an embedded local API and send assistant/project requests
  through the API.

### 1.2 What is not actually complete

- The default EEEE runtime is `chatgpt_web`, not Ollama. There is no Ollama
  adapter in `apps/eeee/app/agent`; local Ollama adapters exist elsewhere in
  ISEOL but are not the default EEEE conversation path.
- Routing is deterministic trigger-phrase matching. It is not a general
  natural-language assistant router.
- `personal-secretary`, `knowledge-documents`, and `presence` are planning
  capabilities. They return a plan/selection response but do not yet perform
  calendar, file, reminder, or device actions.
- Conversation turns are not a first-class EEEE data model. Existing durable
  data focuses on project requests, tasks, runs, events, evidence, and project
  memory.
- Project memory is not the same as chat memory. It stores verified project
  outcomes; it does not provide a complete user-visible conversation archive.
- Notion and GitHub have partial adapter paths. Gmail and Google Calendar are
  not complete EEEE core capabilities.
- The plugin host is a protocol/lifecycle foundation, not a finished
  end-user marketplace or GPT-style install/login catalog.
- ClaimLatch defaults to advisory mode. A missing ClaimLatch adapter does not
  make ordinary local planning a verified claim, and it must not be described
  as full production trust enforcement.
- Project auto-execution defaults to false. A project can be provisioned
  without the agent run being automatically executed.
- The current desktop build wiring still includes heavy optional runtime
  assets in the same packaging path. This prevents the core from being
  genuinely lightweight.
- The current working tree used for the audit was dirty: tracked EEEE/ISEOL
  files had uncommitted changes and many temporary test directories existed.
  Those changes belong to the user and are not silently folded into this
  design.

### 1.3 Verification boundary

Running the EEEE suite from `apps/eeee` produced **450 passed, 1 skipped, 1
warning**. This proves the deterministic Python unit/API/contract suite in
that environment. It does not prove live Ollama responses, ChatGPT Web login,
real external connector actions, packaged desktop startup, or end-to-end
project execution with production credentials.

The test suite must therefore report these as separate evidence classes:

1. deterministic unit and contract tests;
2. local-runtime smoke tests;
3. packaged desktop smoke tests;
4. live provider/connector tests;
5. user-flow acceptance tests.

No green unit-test count may be reported as proof of all five classes.

## 2. Target product boundary

### 2.1 EEEE Core is responsible for

- one local assistant identity and conversation lifecycle;
- storing every user message and assistant response durably;
- local Ollama connection and model status;
- lightweight intent classification and capability selection;
- context-window construction from recent conversation plus approved memory;
- local task lifecycle and resumable status;
- user approval before workspace, network, or external side effects;
- persistent memory candidates, explicit user memory, search, editing, and
  revocation;
- events, notifications, errors, and restart recovery;
- a stable local API used by Desktop, Chat History, Mobile, and plugins;
- connector/plugin metadata, permission declarations, and health state.

### 2.2 EEEE Core is not responsible for

- implementing Gmail, Calendar, Notion, GitHub, or other provider APIs;
- driving Chrome or ChatGPT Web during ordinary startup;
- creating a second database for each plugin;
- implementing ISEOL's Agent decomposition and execution internals;
- rendering the Desktop UI inside the kernel;
- treating an LLM's natural-language statement as proof of completed work;
- silently installing unknown code or granting provider permissions.

### 2.3 Desktop Shell is responsible for

- the cat/pet surface, input focus, speech bubble, tray state, and local
  notifications;
- calling the Core API without owning assistant business logic;
- rendering streaming, completed, failed, cancelled, and interrupted states;
- opening an optional control center only when the user asks for it;
- never stealing focus or opening an external browser/window automatically for
  an ordinary response;
- preserving the user's last safe position and visibility preference.

The Desktop Shell must not instantiate Ollama, write SQLite tables, call
provider APIs, or decide whether a response is trusted.

## 3. Target runtime topology

```text
                ┌──────────────────────────────┐
                │ EEEE Core                    │
                │ loopback API + SQLite        │
                │ Ollama adapter               │
                │ conversations + memory       │
                │ router + policy + events     │
                └──────────────┬───────────────┘
                               │ localhost protocol
              ┌────────────────┼────────────────┐
              │                │                │
       Desktop Shell     Chat History       Mobile/Plugins
       PySide6 only      optional UI        optional clients

       Optional capability workers, started only when used:
       ISEOL / ChatGPT Web / Gmail / Calendar / Notion / GitHub
```

There is one Core process and one SQLite source of truth. Optional workers may
be isolated subprocesses, but no optional worker is started on Core boot when
it is not installed or selected.

## 4. Core request and response logic

Every user turn follows one durable state machine:

```text
received
  -> persisted_user_message
  -> classified
  -> awaiting_approval | generating | executing
  -> streaming
  -> completed | failed | cancelled | interrupted
```

### 4.1 Inbound turn

1. The Core creates a `requestId` and persists the user message before calling
   an AI provider.
2. The Core loads only the current conversation's bounded recent context and
   explicitly eligible memories.
3. A deterministic safety pre-router detects explicit capability requests and
   side-effect verbs. It never executes an action merely because a model
   suggested one.
4. For ordinary conversation or ambiguous intent, the Core calls the local
   Ollama adapter with a structured prompt contract.
5. The model may return a normal answer, a clarification request, or a typed
   action proposal. Invalid structured output becomes an error/clarification,
   never a fabricated success.
6. An action proposal is shown as a plan and waits for approval when its
   side-effect level requires it.
7. The Core streams answer text to clients and persists the final assistant
   message with its status and metadata.
8. The Core emits durable lifecycle events so a restarted UI can reconstruct
   the current state.

### 4.2 Restart and failure behavior

- A user message is never lost because the model is unavailable.
- A response left in `streaming` when Core stops becomes `interrupted` on the
  next startup and offers retry.
- A timeout is an explicit failure with a retryable error code.
- A provider error is not converted into a normal assistant answer.
- A completed response is never deleted by the five-second UI bubble timer.

## 5. Data model

Conversation transcript and long-term memory are separate by design.

### 5.1 Conversation tables

`conversations`:

- `id`, `title`, `created_at`, `updated_at`, `archived_at`;
- `active_message_id` and optional UI metadata.

`messages`:

- `id`, `conversation_id`, `sequence`;
- `role`: `user`, `assistant`, `system`, or `tool`;
- `content`, `status`, `created_at`, `completed_at`;
- `request_id`, `provider`, `model`, `error_code`, and bounded metadata.

The database stores full transcript text locally. API responses use cursor
pagination and never load an unlimited conversation into the UI or model
context.

### 5.2 Long-term memory

Memory has explicit types and lifecycle states:

- user preference;
- user fact;
- project fact;
- verified success/failure pattern;
- QA/regression rule;
- revoked or superseded memory.

Raw conversation is not promoted automatically. Promotion requires either an
explicit user instruction or a verified outcome with provenance. Every active
memory keeps source message/artifact IDs, scope, confidence, and revocation
metadata.

SQLite FTS5 is the first search implementation. A vector database is out of
scope until actual retrieval measurements show that FTS5 is insufficient.

## 6. Capability and plugin boundary

The first built-in capabilities are:

- `conversation`: real local Ollama conversation;
- `memory`: inspect, remember, edit, forget, and search approved memory;
- `desktop-presence`: local UI state only;
- `project-execution`: deferred capability that loads ISEOL only when used.

External services are plugins. A plugin declares:

- identity/version and entry point;
- actions and schemas;
- permissions and side-effect level;
- authentication flow;
- health check and protocol version;
- memory read/write scope.

Installation, authentication, connection, invocation, failure, and removal
are separate states. Removing a plugin removes its active registration, not
the conversation or audit history.

The first Chat History plugin consumes Core conversation APIs. It does not
start another Ollama process and does not own a second transcript database.

## 7. Desktop behavior contract

The Desktop Shell has explicit presentation states:

- `idle`: cat is visible, bubble hidden;
- `input`: bubble is focused and editable;
- `submitting`: input is locked while the request is accepted;
- `streaming`: answer is being generated and the bubble cannot disappear;
- `answer`: final answer is visible;
- `error`: actionable failure is visible;
- `hidden`: bubble is hidden without deleting state.

Rules:

- Bubble height is content-driven, never a fixed 24px/one-line height.
- Text is measured in a dedicated layout area with horizontal and vertical
  padding before the asset/background is sized.
- User input and assistant output use the same centered text layout contract.
- Clicking an answer opens a fresh input state instead of extending the answer
  timer.
- The five-second timer starts only after a terminal response state.
- Focused input, active streaming, or a pending approval pauses auto-hide.
- The timer hides the bubble only; it never cancels a Core request or deletes a
  saved message.
- Core never calls window activation/raise for a normal response.
- Long tasks use tray/status indicators and an optional control center rather
  than opening ChatGPT, Chrome, or a terminal over the user's work.

## 8. Lightweight packaging and performance

### Core distribution

- Python/FastAPI/SQLite/Ollama adapter only;
- no PySide6 requirement;
- no Node, Playwright, ISEOL, OpenHands, or provider SDK imports at startup;
- lazy imports for optional capabilities;
- one loopback service and one database.

### Desktop distribution

- PySide6 is included only in the Desktop Shell package;
- the shell is one Qt process and calls Core over localhost;
- plugin UIs are not allowed to start one full Qt runtime per installed plugin;
- optional plugin windows use a shared host or a thin client when isolation is
  necessary.

### Runtime targets

- Core must start and answer `/health` without Ollama, ISEOL, Node, Chrome, or
  any plugin installed.
- Desktop startup must not spawn Node, Chrome, ChatGPT Web, ISEOL, or an
  optional plugin.
- A normal conversation must not initialize the project runtime.
- Core route overhead excluding Ollama must be measured with a local benchmark
  and kept below 100ms p95 for a warm process.
- No UI network call may block the Qt event loop.
- Conversation rendering and API reads must stay cursor/page bounded.

## 9. Trust and safety rules

- Ordinary local conversation is explicitly labelled as assistant output, not
  verified external fact.
- Workspace writes, commands, network calls, external messages, deletion,
  publishing, and deployment require typed action plans and approval policy.
- ClaimLatch and deterministic QA are mandatory for release, external side
  effects, and memory promotion. They are not launched for a harmless local
  greeting.
- Provider credentials never enter conversation content, event payloads, or
  plugin logs.
- Model output cannot choose an arbitrary executable, path, or plugin command.
- Unknown plugin code requires explicit installation approval.

## 10. Migration strategy

The redesign preserves existing project data and avoids a destructive rewrite.

1. Add the Core conversation/message contract and Ollama adapter beside the
   legacy agent runtime.
2. Make the new conversation capability the default assistant path.
3. Add restart-safe request state and transcript persistence.
4. Move the current keyword router behind a compatibility adapter and add the
   structured local router path.
5. Extract the Desktop Shell so it only calls Core APIs.
6. Move project execution, ChatGPT Web, and OpenHands construction behind lazy
   capability factories.
7. Keep legacy project/request endpoints during migration and mark them as
   compatibility surfaces.
8. Split packaging so optional runtimes are not in the Core distribution.
9. Add live local-Ollama, packaged Desktop, restart, and user-flow tests.
10. Only after EEEE Core is stable, resume Chat History UI and ISEOL work.

No migration step may delete the existing SQLite database or silently reset
conversation/project identity.

## 11. Acceptance criteria

EEEE Core redesign is not complete until all of these are demonstrated:

1. A clean Core installation starts without ISEOL, ChatGPT Web, Node, Chrome,
   PySide6, or plugins.
2. Ollama is the default local conversation provider when a local model is
   configured; unavailable Ollama produces an explicit waiting/error state.
3. A user message is persisted before generation and the assistant response is
   persisted after completion or failure.
4. Restarting Core preserves the transcript and marks interrupted turns
   retryable.
5. Long responses render without clipping, fixed-height truncation, or
   unwanted bubble disappearance.
6. Clicking an answer starts a new input turn.
7. A normal response never opens or focuses an external window.
8. Personal-secretary, memory, and conversation flows have real behavior or
   explicitly report that the capability is not installed; they do not return
   a fake “completed” result.
9. Project execution is unavailable unless its optional runtime is configured,
   and that state is visible without breaking ordinary chat.
10. External actions and memory promotion fail closed without required
    approval/evidence.
11. Core and Desktop package sizes/process counts are measured separately, and
    optional ISEOL/Playwright assets are absent from the Core package.
12. Verification reports distinguish deterministic tests, local runtime smoke,
    packaged desktop smoke, live provider tests, and user-flow acceptance.

## 12. Explicit non-goals for this redesign

- Building ISEOL Agent teams inside EEEE Core;
- implementing Gmail, Calendar, Notion, GitHub, or other provider business
  logic in the Core;
- creating a hosted EEEE account or cloud database;
- building a public plugin marketplace;
- adding a vector database before SQLite FTS5 is measured and found
  insufficient;
- claiming that passing unit tests proves live AI or connector behavior.

