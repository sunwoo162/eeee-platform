# EEEE General Assistant and Optional Plugins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make EEEE the always-available personal assistant and route only
installed, connected plugins to specialized work without making project
development the default behavior.

**Architecture:** Keep one canonical EEEE assistant route. Add a direct
conversation fallback and a plugin-aware capability catalog above the existing
kernel, while preserving ISEOL as the built-in project capability and
ClaimLatch as the built-in trust boundary. Optional service integrations remain
outside the default installation and become routable only after registration,
permission approval, connection, and health success.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, existing local
execution/event/ClaimLatch contracts, PySide6 desktop shell, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-eeee-core-optional-plugins-design.md`

## Global Constraints

- Every user message enters EEEE first.
- EEEE must answer or explain the next action even when no optional plugin is installed.
- ISEOL is built-in project development, not EEEE's identity.
- ClaimLatch profile `claimlatch-v0.2.0` remains attached to assistant and plugin results.
- Notion, Calendar, GitHub, Slack, and similar services are not default-installed.
- A paused, disconnected, failed, or unapproved plugin cannot be selected or reported as successful.
- Existing project, QA, memory, desktop, mobile, and plugin lifecycle APIs remain backward compatible.
- Desktop default mode exposes only the EEEE character and speech bubble; detailed project/plugin views are secondary.

## Review Focus

- A normal conversation with zero optional plugins must not become project clarification; covered in Task 1.
- A project request must still select ISEOL and preserve the existing Todo QA/release path; covered in Task 4.
- An unavailable optional plugin must produce a truthful install/connect response and no external side effect; covered in Task 3.
- Paused/disconnected plugins must be absent from automatic routing; covered in Task 2.
- A plugin result must preserve execution identity and ClaimLatch metadata; covered in Task 3.

---

### Task 1: EEEE direct conversation fallback

**Files:**
- Modify: `apps/eeee/app/assistant/models.py`
- Modify: `apps/eeee/app/assistant/router.py`
- Modify: `apps/eeee/app/kernel/service.py`
- Modify: `apps/eeee/app/assistant/service.py`
- Test: `apps/eeee/tests/assistant/test_router.py`
- Test: `apps/eeee/tests/assistant/test_assistant_service.py`
- Test: `apps/eeee/tests/kernel/test_service.py`

**Interfaces:**
- Add `general_conversation` as the zero-plugin fallback capability.
- `CapabilityRouter.select()` returns a selected direct-conversation candidate
  when no specialized trigger matches instead of `needs_clarification`.
- The direct handler returns a truthful `completed`, `planned`, or `blocked`
  result without creating a project.

- [ ] **Step 1: Write failing tests**

  Assert that `"오늘 날씨 말고 오늘 할 일 정리하는 방법 알려줘"` and a generic
  greeting select `general_conversation`, do not create a project, and attach
  `claimlatch-v0.2.0` response verification metadata. Assert an explicit
  project request still selects `project-execution`.

- [ ] **Step 2: Run focused tests and verify the expected failure**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/assistant/test_router.py apps/eeee/tests/assistant/test_assistant_service.py apps/eeee/tests/kernel/test_service.py`

- [ ] **Step 3: Implement the direct assistant capability**

  Add the fallback descriptor and handler wiring. Keep provider/model access
  behind the existing agent runtime boundary; if no runtime is configured,
  return an explicit advisory response rather than inventing an answer.

- [ ] **Step 4: Run focused tests and verify they pass**

- [ ] **Step 5: Commit**

  `git add apps/eeee/app/assistant apps/eeee/app/kernel apps/eeee/tests/assistant apps/eeee/tests/kernel && git commit -m "feat: make EEEE a general assistant by default"`

### Task 2: Optional plugin capability catalog and routing eligibility

**Files:**
- Modify: `apps/eeee/app/plugins/models.py`
- Modify: `apps/eeee/app/plugins/host.py`
- Modify: `apps/eeee/app/runtime/store.py`
- Modify: `apps/eeee/app/assistant/registry.py`
- Modify: `apps/eeee/app/assistant/router.py`
- Test: `apps/eeee/tests/plugins/test_manifest.py`
- Test: `apps/eeee/tests/plugins/test_host.py`
- Test: `apps/eeee/tests/assistant/test_registry.py`
- Test: `apps/eeee/tests/assistant/test_router.py`

**Interfaces:**
- Extend `PluginManifest` with optional capability descriptors and trigger
  phrases, preserving old manifests with empty lists.
- Add `PluginHost.routing_capabilities()` returning only connected, healthy,
  permission-approved plugin capabilities.
- Add registry eligibility metadata without importing plugin implementations.

- [ ] **Step 1: Write failing tests**

  Assert old manifests still parse, optional manifests expose capabilities,
  `available`/`paused`/`failed` registrations are excluded, and a connected
  plugin becomes routable only after a successful health check.

- [ ] **Step 2: Run tests and verify failure**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/plugins apps/eeee/tests/assistant/test_registry.py apps/eeee/tests/assistant/test_router.py`

- [ ] **Step 3: Implement catalog projection and router filtering**

  Project plugin registration state into the router at request time so pause,
  disconnect, and removal take effect without restarting EEEE.

- [ ] **Step 4: Run tests and verify pass**

- [ ] **Step 5: Commit**

  `git add apps/eeee/app/plugins apps/eeee/app/runtime/store.py apps/eeee/app/assistant && git commit -m "feat: route only enabled optional plugins"`

### Task 3: Missing-plugin, permission, and trust-aware assistant responses

**Files:**
- Modify: `apps/eeee/app/assistant/models.py`
- Modify: `apps/eeee/app/kernel/service.py`
- Modify: `apps/eeee/app/assistant/service.py`
- Modify: `apps/eeee/app/api/routes.py`
- Test: `apps/eeee/tests/api/test_assistant_routes.py`
- Test: `apps/eeee/tests/plugins/test_routes.py`
- Test: `apps/eeee/tests/trust/test_pipeline.py`

**Interfaces:**
- Add structured route status `plugin_required` with plugin ID, display name,
  required permissions, and suggested install/connect action.
- Never call a plugin action while it is absent, paused, disconnected, or
  unapproved.
- Preserve the existing execution envelope, event ledger, and ClaimLatch
  response verification fields for plugin results.

- [ ] **Step 1: Write failing API tests**

  Request a Notion-style action with no registration and assert a structured
  `plugin_required` response with no project creation or plugin invocation.
  Pause a connected fixture and assert the same safe behavior. Assert a valid
  connected invocation includes execution ID, plugin ID, and ClaimLatch policy.

- [ ] **Step 2: Run tests and verify failure**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/api/test_assistant_routes.py apps/eeee/tests/plugins/test_routes.py apps/eeee/tests/trust/test_pipeline.py`

- [ ] **Step 3: Implement structured missing-plugin routing and trust mapping**

  Keep installation/connection as an explicit user action. Map plugin host
  failures to truthful assistant responses and durable blocked/failed
  envelopes; never convert them to completed output.

- [ ] **Step 4: Run tests and verify pass**

- [ ] **Step 5: Commit**

  `git add apps/eeee/app/assistant apps/eeee/app/kernel apps/eeee/app/api/routes.py apps/eeee/tests/api/test_assistant_routes.py apps/eeee/tests/plugins/test_routes.py apps/eeee/tests/trust/test_pipeline.py && git commit -m "feat: report optional plugin requirements safely"`

### Task 4: Built-in ISEOL project routing regression

**Files:**
- Modify: `apps/eeee/app/assistant/registry.py`
- Modify: `apps/eeee/app/kernel/capabilities.py`
- Test: `apps/eeee/tests/e2e/test_todo_generation.py`
- Test: `apps/eeee/tests/e2e/test_live_agent_todo.py`
- Test: `apps/eeee/tests/project_runtime/test_todo_runner.py`

**Interfaces:**
- Preserve `project-execution` as the built-in ISEOL adapter.
- Keep the existing plan → specialist agents → QA → ClaimLatch → release and
  memory promotion flow unchanged for project requests.

- [ ] **Step 1: Add a regression assertion**

  Assert `Todo 앱 만들어줘` selects ISEOL/project execution, creates the
  expected FSD workspace, emits independent QA and release artifacts, and
  finishes only with ClaimLatch PASS.

- [ ] **Step 2: Run the regression and verify it passes**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/e2e/test_todo_generation.py apps/eeee/tests/e2e/test_live_agent_todo.py apps/eeee/tests/project_runtime/test_todo_runner.py`

- [ ] **Step 3: Commit**

  `git add apps/eeee/app/assistant apps/eeee/app/kernel/capabilities.py apps/eeee/tests/e2e apps/eeee/tests/project_runtime/test_todo_runner.py && git commit -m "test: preserve ISEOL project execution through EEEE"`

### Task 5: EEEE-first desktop surface and end-to-end verification

**Files:**
- Modify: `apps/eeee/app/desktop/window.py`
- Modify: `apps/eeee/app/desktop/client.py`
- Modify: `apps/eeee/app/static/index.html`
- Modify: `apps/eeee/app/static/app.js`
- Test: `apps/eeee/tests/desktop/test_window.py`
- Test: `apps/eeee/tests/e2e/test_assistant_project_runtime.py`
- Test: `apps/eeee/tests/desktop/test_runtime.py`
- Modify: `README.md`

**Interfaces:**
- Default desktop mode remains only the EEEE character and speech bubble.
- Project/plugin details appear only after a relevant route result or explicit
  workspace action.
- Korean remains the default UI language with English selection.

- [ ] **Step 1: Write failing UI/E2E tests**

  Assert a normal assistant request does not expose project-only controls,
  a project request reveals project progress only after ISEOL selection, and
  the packaged desktop self-tests still pass.

- [ ] **Step 2: Implement EEEE-first labels and secondary detail surfaces**

  Remove project-specific default copy, preserve Enter submission, and show
  plugin-required guidance as a speech-bubble response.

- [ ] **Step 3: Run complete verification**

  Run:

  ```powershell
  C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests
  node --check apps/eeee/app/static/app.js
  .\scripts\build-desktop.ps1 -PythonPath C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe
  build\desktop\GleaveDesktop.exe --self-test
  build\desktop\GleaveDesktop.exe --gui-self-test
  ```

- [ ] **Step 4: Commit**

  `git add apps/eeee/app/desktop apps/eeee/app/static apps/eeee/tests/desktop apps/eeee/tests/e2e README.md && git commit -m "feat: make EEEE the primary assistant surface"`
