# EEEE Core Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the EEEE desktop core reliable for real use before adding more plugins: input must not disappear, active work must not be hidden by the idle timer, replies must remain readable, local conversation routing must stay separate from project status, and restart/desktop behavior must remain stable.

**Architecture:** Keep the pet window as the lightweight presentation shell, but give Quick Chat an explicit conversation phase instead of inferring state from widget visibility and one overloaded `detail` label. Keep project/background status on its own path, and make the bubble renderer consume measured text geometry without a fixed height. Preserve the existing local SQLite/Ollama source of truth and plugin APIs; this plan stabilizes the core and does not implement new external plugins.

**Tech Stack:** Python 3.12, PySide6, FastAPI, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-eeee-desktop-assistant-product-design.md`

## Global Constraints

- EEEE remains the first user-facing entry point.
- Basic conversation stays on the local Ollama lane; ChatGPT Web is only an explicit/required provider path.
- Local Desktop and SQLite remain the source of truth.
- A background refresh or project-profile error must not overwrite an active conversation reply.
- The pet and its surfaces must not auto-open a browser, terminal, or ChatGPT window during ordinary conversation.
- Bubble text must wrap and grow from measured content; no fixed 24px/one-line height assumption.
- No production change is accepted without a regression test that failed before the change and a fresh full-suite run.

## Review Focus

- A user keeps typing for more than five seconds: the draft and input surface remain visible.
- A request takes more than five seconds: the processing state remains visible until the request finishes.
- A second Enter event arrives while a request is running: it does not clear or enqueue a second request.
- A Korean or long multi-line reply/error is shown: every line remains readable inside the bubble and the bubble grows naturally.
- A background refresh returns a missing project profile while a conversation is active: the user still sees the assistant response, not the internal project error.

### Task 1: Establish the failing real-use desktop contract

**Files:**
- Modify: `apps/eeee/tests/desktop/test_window.py`
- Modify: `apps/eeee/tests/desktop/test_session.py`

**Interfaces:**
- Consumes: existing `PetWindow`, `DesktopSession`, and test clients.
- Produces: regression tests for draft timeout, processing timeout, active reply isolation, and refresh failure handling.

- [x] **Step 1: Write failing tests**

  Add tests that prove:

  - a non-empty draft stops the idle timer and survives a timer event;
  - a slow request keeps Quick Chat visible while `_busy` is true;
  - a background refresh cannot replace the active assistant message;
  - a `DesktopSession.route()` still returns the assistant route when a post-route desktop-state refresh raises a missing-profile error.

- [x] **Step 2: Run the focused tests and verify RED**

  Run from `apps/eeee`:

  ```powershell
  $env:PYTHONPATH='.'; python -m pytest tests/desktop/test_window.py tests/desktop/test_session.py -q
  ```

  Expected: the new real-use tests fail for the current timer/state behavior.

- [x] **Step 3: Commit the RED tests**

  ```powershell
  git add apps/eeee/tests/desktop/test_window.py apps/eeee/tests/desktop/test_session.py
  git commit -m "test: capture EEEE desktop conversation regressions"
  ```

### Task 2: Separate conversation phases from background status

**Files:**
- Create: `apps/eeee/app/desktop/conversation_state.py`
- Modify: `apps/eeee/app/desktop/window.py`
- Modify: `apps/eeee/app/desktop/session.py`
- Modify: `apps/eeee/tests/desktop/test_window.py`
- Modify: `apps/eeee/tests/desktop/test_session.py`

**Interfaces:**
- Consumes: Task 1 regression tests.
- Produces: explicit input/processing/typing/reply/hidden phase handling and a session route that preserves a valid assistant response when status refresh is unavailable.

- [x] **Step 1: Write the pure phase-policy tests first**

  Add a small unit contract for the conversation state policy: empty input may expire, non-empty draft may not expire, processing/typing may not expire, and a completed reply may expire.

- [x] **Step 2: Run the policy tests and verify RED**

  Run the new state test directly and confirm it fails because the state policy does not exist.

- [x] **Step 3: Implement the minimal state policy**

  Add a small enum/dataclass module with no Qt dependency. Make the policy answer whether the surface should remain visible and whether the five-second hide timer is allowed.

- [x] **Step 4: Wire the policy into `PetWindow`**

  - stop the hide timer while a draft is non-empty, a request is busy, or reply typing is active;
  - start the timer only for an empty input surface or a completed reply;
  - guard the timer callback so a race cannot clear a draft or hide an active request;
  - clear the input only after the request has been accepted into the running state;
  - keep background refreshes on the status widgets and do not use them as conversation text;
  - make reply-bubble clicks transition to a fresh input phase without extending the old reply.

- [x] **Step 5: Harden `DesktopSession.route()`**

  Preserve the assistant route result when the follow-up project/status snapshot fails. Expose the status failure separately for the status panel instead of converting it into the conversation reply.

- [x] **Step 6: Run focused tests and verify GREEN**

  ```powershell
  $env:PYTHONPATH='.'; python -m pytest tests/desktop/test_window.py tests/desktop/test_session.py -q
  ```

- [x] **Step 7: Commit the state fix**

  ```powershell
  git add apps/eeee/app/desktop/conversation_state.py apps/eeee/app/desktop/window.py apps/eeee/app/desktop/session.py apps/eeee/tests/desktop/test_window.py apps/eeee/tests/desktop/test_session.py
  git commit -m "fix: keep EEEE conversation state alive during work"
  ```

### Task 3: Make bubble geometry and text rendering deterministic

**Files:**
- Create: `apps/eeee/app/desktop/bubble_layout.py`
- Modify: `apps/eeee/app/desktop/window.py`
- Modify: `apps/eeee/tests/desktop/test_window.py`
- Create: `apps/eeee/tests/desktop/test_bubble_layout.py`

**Interfaces:**
- Consumes: Task 2's explicit reply/typing lifecycle.
- Produces: a pure measured bubble layout helper used by both reply and Quick Chat surfaces.

- [x] **Step 1: Write failing layout tests**

  Cover one, two, three, ten, and long Korean/error lines; assert that the measured text rectangle contains the document height, that width presets stay bounded, and that there is no fixed one-line height.

- [x] **Step 2: Run the layout tests and verify RED**

  Run `tests/desktop/test_bubble_layout.py -q` and confirm the helper contract fails before implementation.

- [x] **Step 3: Implement measured layout**

  Move width selection, text-document measurement, body padding, tail-safe height, and centered text rectangle calculations into the pure helper. Keep the bubble asset tail below the text area and return a complete geometry for every line count.

- [x] **Step 4: Use the helper in both Qt bubble surfaces**

  Remove duplicated width/height assumptions from `_SpeechBubbleLabel` and `_SpeechBubbleFrame`. Do not add a maximum height; constrain only the rendered batch to the available screen and keep the text scroll/expand behavior readable when necessary.

- [x] **Step 5: Run focused UI/layout tests and verify GREEN**

  ```powershell
  $env:PYTHONPATH='.'; python -m pytest tests/desktop/test_bubble_layout.py tests/desktop/test_window.py -q
  ```

- [x] **Step 6: Commit the rendering fix**

  ```powershell
  git add apps/eeee/app/desktop/bubble_layout.py apps/eeee/app/desktop/window.py apps/eeee/tests/desktop/test_bubble_layout.py apps/eeee/tests/desktop/test_window.py
  git commit -m "fix: render EEEE bubbles from measured text geometry"
  ```

### Task 4: Close the local conversation delivery and persistence gaps

**Files:**
- Modify: `apps/eeee/app/desktop/client.py`
- Modify: `apps/eeee/app/desktop/session.py`
- Modify: `apps/eeee/app/memory/store.py`
- Modify: `apps/eeee/tests/desktop/test_session.py`
- Modify: `apps/eeee/tests/api/test_assistant_routes.py`
- Modify: `apps/eeee/tests/memory/test_conversation_history.py`

**Interfaces:**
- Consumes: Task 2's route/state separation.
- Produces: one explicit `desktop-default` conversation id through the desktop client/API and durable ordered turns available for the future conversation-history plugin.

- [x] **Step 1: Write failing API/client/storage tests**

  Assert that the desktop client sends `conversationId=desktop-default`, that user and assistant turns remain ordered after restart, and that a failed status refresh does not duplicate or drop a completed assistant turn.

- [x] **Step 2: Run the tests and verify RED**

  Run the focused API, session, and memory tests and confirm the missing conversation-id/persistence contract fails where applicable.

- [x] **Step 3: Implement the smallest end-to-end fix**

  Thread the conversation id through the desktop client and route payload, use the existing SQLite conversation table as the only source of truth, and add cursor-based reads only if required by the persistence contract. Do not create a second chat database.

- [x] **Step 4: Run focused tests and verify GREEN**

  ```powershell
  $env:PYTHONPATH='.'; python -m pytest tests/desktop/test_session.py tests/api/test_assistant_routes.py tests/memory/test_conversation_history.py -q
  ```

- [x] **Step 5: Commit the persistence fix**

  ```powershell
  git add apps/eeee/app/desktop/client.py apps/eeee/app/desktop/session.py apps/eeee/app/memory/store.py apps/eeee/tests/desktop/test_session.py apps/eeee/tests/api/test_assistant_routes.py apps/eeee/tests/memory/test_conversation_history.py
  git commit -m "fix: preserve EEEE local conversation delivery"
  ```

### Task 5: Verify the complete core user flow and package the result

**Files:**
- Modify only if required by failing acceptance tests: `apps/eeee/app/desktop/*`, `apps/eeee/app/assistant/*`, `apps/eeee/app/memory/*`, and their tests.
- Create: `docs/superpowers/sdd/2026-10-15-eeee-core-stability/progress.md`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: a verified core baseline ready for later plugin work, with no claim that plugins themselves are implemented here.

- [x] **Step 1: Run the desktop acceptance flow**

  Exercise fresh launch, click-to-input, empty five-second dismissal, draft longer than five seconds, Enter send, slow response, long Korean reply, reply click-to-new-input, background refresh error, restart persistence, and no automatic ChatGPT/terminal window.

- [x] **Step 2: Run the full EEEE suite from the correct directory**

  ```powershell
  $env:PYTHONPATH='.'; python -m pytest tests -q
  ```

  Expected: zero failures; warnings must be reported, not hidden.

- [x] **Step 3: Build and launch the current desktop artifact**

  Use the repository's existing desktop build command, launch the resulting executable, verify the process path matches the branch, and capture the actual user flow rather than relying only on unit tests.

- [x] **Step 4: Perform a final self-review**

  Re-read the spec and diff, verify no plugin implementation was prematurely coupled into the core, and record any deferred issues explicitly.

- [x] **Step 5: Commit packaging/documentation changes**

  ```powershell
  git add docs/superpowers/plans/2026-10-15-eeee-core-stability.md docs/superpowers/sdd/2026-10-15-eeee-core-stability/progress.md
  git commit -m "docs: record EEEE core stability verification"
  ```

### Task 6: Close the Windows local-AI shutdown gap

**Files:**
- Create: `apps/eeee/app/storage/connection.py`
- Modify: `apps/eeee/app/storage/sqlite.py`
- Modify: `apps/eeee/app/memory/store.py`
- Modify: `apps/eeee/app/integrations/claimlatch_audit.py`
- Modify: `apps/eeee/app/mobile/bridge.py`
- Test: `apps/eeee/tests/storage/test_sqlite.py`
- Test: `apps/eeee/tests/api/test_provider_wiring.py`

- [x] **Step 1: Reproduce the real failure** — a local Ollama route returned successfully, but Windows could not delete `state.sqlite3` after app shutdown.
- [x] **Step 2: Add regression coverage** — connection-context closure and full app shutdown cleanup are covered.
- [x] **Step 3: Implement the shared context-closing SQLite connection** — all EEEE durable stores now release handles at transaction-context exit.
- [x] **Step 4: Verify** — focused storage/provider tests pass; real Ollama responds through the local lane; the full core product gate passes.
