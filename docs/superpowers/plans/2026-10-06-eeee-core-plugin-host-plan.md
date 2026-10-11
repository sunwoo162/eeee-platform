# EEEE Core and Plugin Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the lightweight local Gleave body that combines EEEE, ISEOL,
ClaimLatch, durable evidence, the assistant surface, and a separate Plugin
Host contract without bundling optional plugin implementations.

**Architecture:** Normalize all built-in capabilities, ISEOL work, and future
plugins around shared execution envelopes, local events, permissions, and
evidence. Keep EEEE, ISEOL, and ClaimLatch in the core distribution; make the
Plugin Host manifest/protocol/permission layer the only core-facing plugin
surface. Add a project-map API and UI that renders ISEOL's live task structure,
commits, QA, ClaimLatch, and evidence rather than a flat run list.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, local loopback
HTTP, subprocess isolation for plugin fixtures, vanilla JavaScript/CSS,
pytest, and Node's built-in test runner. No optional-provider runtime
dependency in the core.

**Spec:** `docs/superpowers/specs/2026-10-06-eeee-core-plugin-host-design.md`

## Global Constraints

- A clean local installation starts EEEE, ISEOL, ClaimLatch integration, durable memory/state, the Desktop assistant, and the project view without installing optional plugins.
- Plugin implementations live outside this project; the core contains only a lightweight Plugin Host and stable contracts.
- ISEOL and ClaimLatch are built-in body components and cannot be moved to optional plugins.
- Every capability and tool invocation produces an `ExecutionEnvelope` and publishes local lifecycle events.
- ClaimLatch v0.2.0 is mandatory for AI claims, actions, release, and memory promotion; deterministic QA remains a separate check.
- The core must work with zero external plugins and must never report a missing, denied, disconnected, or failed plugin action as successful.
- No hosted login service, mandatory central server, or provider-specific implementation is introduced.
- Existing project, memory, ClaimLatch, desktop, mobile, and request/run APIs remain backward compatible.

## Review Focus

- A clean installation with zero plugins can create a sample project and show its project map; test in Task 7.
- A denied permission or failed plugin health check stops the action and leaves an auditable failed envelope; test in Task 5.
- A plugin process crash is isolated from the kernel and reported as a plugin failure; test in Task 5.
- A stale project revision cannot publish trusted results or overwrite the current map state; test in Tasks 1, 3, and 4.
- A plugin manifest with unknown capabilities, malformed schemas, or excessive permissions is rejected before registration; test in Task 5.

---

### Task 1: Shared execution, event, permission, and evidence contracts

**Files:**
- Create: `apps/eeee/app/contracts/__init__.py`
- Create: `apps/eeee/app/contracts/execution.py`
- Create: `apps/eeee/app/contracts/events.py`
- Create: `apps/eeee/app/contracts/permissions.py`
- Modify: `apps/eeee/app/assistant/models.py`
- Test: `apps/eeee/tests/contracts/test_execution.py`
- Test: `apps/eeee/tests/contracts/test_events.py`
- Test: `apps/eeee/tests/contracts/test_permissions.py`

**Interfaces:**
- Produces `ExecutionEnvelope`, `ExecutionStatus`, `SideEffectLevel`, and
  `ExecutionError` Pydantic models.
- Produces `EventEnvelope` and `LocalEventBus.publish(event) -> EventEnvelope`
  with subscriber registration and cursor-based replay.
- Produces `PermissionScope`, `PermissionRequest`, and
  `PermissionDecision` models with explicit allow/deny/approval states.
- `ExecutionEnvelope` carries `executionId`, `requestId`, optional `projectId`
  and `projectRevision`, `capabilityId`, `toolId`, actor, input/output,
  evidence IDs, ClaimLatch receipt ID, QA report ID, side-effect level,
  approval state, timestamps, and error.

- [ ] **Step 1: Write failing contract tests**

  Assert strict validation of required IDs, stable JSON aliases, allowed status
  transitions, project revision identity, event cursor ordering, subscriber
  isolation, and permission denial when an action requests a scope that was not
  approved.

- [ ] **Step 2: Run focused tests to verify they fail**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/contracts`

  Expected: FAIL because the shared contracts package does not exist.

- [ ] **Step 3: Implement the contracts and in-memory event bus**

  Use frozen Pydantic models for envelopes and explicit transition validators.
  Keep the event bus transport-neutral so the same events can later be served
  through local HTTP polling or streaming.

- [ ] **Step 4: Run contract tests**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/contracts`

  Expected: all contract tests pass.

- [ ] **Step 5: Commit**

  `git add apps/eeee/app/contracts apps/eeee/app/assistant/models.py apps/eeee/tests/contracts && git commit -m "feat: add shared execution and event contracts"`

### Task 2: Durable execution envelopes and plugin registration storage

**Files:**
- Create: `apps/eeee/app/runtime/__init__.py`
- Create: `apps/eeee/app/runtime/store.py`
- Modify: `apps/eeee/app/storage/sqlite.py`
- Test: `apps/eeee/tests/runtime/test_store.py`

**Interfaces:**
- Produces `ExecutionStore.save(envelope)`, `get(execution_id)`,
  `list_for_project(project_id, revision=None)`, and `append_event(event)`.
- Produces `PluginRegistrationStore.register(manifest)`, `get(plugin_id)`,
  `list(status=None)`, `set_status(plugin_id, status)`, and
  `remove(plugin_id)`.
- Both stores use the existing `SQLiteStore` connection and preserve project
  revision, manifest version, evidence references, and audit timestamps.

- [ ] **Step 1: Write failing persistence tests**

  Pin envelope round-tripping, project/revision filtering, ordered event
  replay, plugin registration status transitions, removal audit retention, and
  stale revision rejection.

- [ ] **Step 2: Run the tests to verify they fail**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/runtime/test_store.py`

  Expected: FAIL because runtime tables and stores are not implemented.

- [ ] **Step 3: Add migration-safe SQLite tables and store methods**

  Add `execution_envelopes`, `execution_events`, `plugin_registrations`, and
  `plugin_audit_events` with JSON payload columns plus queryable identity,
  status, revision, and timestamps. Do not remove or rewrite existing tables.

- [ ] **Step 4: Run persistence tests**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/runtime/test_store.py`

  Expected: all persistence tests pass.

- [ ] **Step 5: Commit**

  `git add apps/eeee/app/runtime apps/eeee/app/storage/sqlite.py apps/eeee/tests/runtime/test_store.py && git commit -m "feat: persist execution and plugin state"`

### Task 3: EEEE kernel capability routing and built-in capability adapters

**Files:**
- Create: `apps/eeee/app/kernel/__init__.py`
- Create: `apps/eeee/app/kernel/service.py`
- Create: `apps/eeee/app/kernel/capabilities.py`
- Modify: `apps/eeee/app/assistant/registry.py`
- Modify: `apps/eeee/app/assistant/router.py`
- Modify: `apps/eeee/app/assistant/service.py`
- Modify: `apps/eeee/app/main.py`
- Test: `apps/eeee/tests/kernel/test_service.py`
- Modify: `apps/eeee/tests/assistant/test_registry.py`
- Modify: `apps/eeee/tests/assistant/test_assistant_service.py`

**Interfaces:**
- Produces `KernelService.route(request: AssistantRequest, context: AssistantContext) -> ExecutionEnvelope`.
- Produces a capability protocol with `descriptor`, `plan(request, context)`,
  and `execute(plan, envelope_context)` methods.
- Registers built-in `project-execution`, `personal-secretary`,
  `knowledge-documents`, and `presence` capabilities without importing any
  optional provider implementation.

- [ ] **Step 1: Write failing kernel tests**

  Assert natural-language and explicit-capability routing, project requests
  selecting built-in project execution, no-plugin assistant startup, event
  publication, and non-project requests not accidentally creating a project.

- [ ] **Step 2: Run focused tests to verify they fail**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/kernel apps/eeee/tests/assistant`

  Expected: FAIL because the kernel service and built-in adapters are not
  wired to the existing registry.

- [ ] **Step 3: Implement the kernel orchestration boundary**

  Move selection, context, policy, envelope creation, and event publication
  behind `KernelService`. Keep existing `AssistantService.route` behavior as a
  compatibility wrapper while delegating project execution to the built-in
  capability.

- [ ] **Step 4: Wire the kernel into `create_app`**

  Instantiate one kernel with the existing store, coordinator, provisioner,
  memory, TrustGate, and local event publisher. Preserve current health,
  desktop, mobile, and request/run routers.

- [ ] **Step 5: Run assistant and kernel tests**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/kernel apps/eeee/tests/assistant apps/eeee/tests/api/test_assistant_routes.py`

  Expected: all kernel, routing, and compatibility tests pass.

- [ ] **Step 6: Commit**

  `git add apps/eeee/app/kernel apps/eeee/app/assistant apps/eeee/app/main.py apps/eeee/tests/kernel apps/eeee/tests/assistant apps/eeee/tests/api/test_assistant_routes.py && git commit -m "feat: add EEEE kernel capability orchestration"`

### Task 4: ISEOL project organization state and project-map API

**Files:**
- Create: `apps/eeee/app/project_view/__init__.py`
- Create: `apps/eeee/app/project_view/models.py`
- Create: `apps/eeee/app/project_view/service.py`
- Modify: `apps/eeee/app/harness/state.py`
- Modify: `apps/eeee/app/harness/coordinator.py`
- Modify: `apps/eeee/app/api/routes.py`
- Modify: `apps/eeee/app/main.py`
- Test: `apps/eeee/tests/project_view/test_service.py`
- Test: `apps/eeee/tests/api/test_project_view_routes.py`

**Interfaces:**
- Produces `ProjectMapNode`, `ProjectMapEdge`, and `ProjectMapSnapshot`.
- Produces `ProjectViewService.get_snapshot(project_id, revision=None) -> ProjectMapSnapshot`.
- Adds `GET /api/projects/{project_id}/map` and
  `GET /api/projects/{project_id}/map/events?cursor=...`.
- Nodes include role, title, status, progress, current commit, changed files,
  ClaimLatch receipt, QA report, evidence IDs, troubleshooting IDs, and
  timestamps. Edges describe task dependencies and handoffs.

- [ ] **Step 1: Write failing project-map tests**

  Seed ISEOL tasks in waiting, active, completed, blocked, and failed states.
  Assert deterministic node grouping, dependency edges, current-node
  selection, commit/evidence attachment, stale revision rejection, and event
  cursors.

- [ ] **Step 2: Run project-map tests to verify they fail**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/project_view apps/eeee/tests/api/test_project_view_routes.py`

  Expected: FAIL because project-map models, service, and routes do not exist.

- [ ] **Step 3: Implement the project-map projection**

  Project the existing ISEOL/harness state and durable execution/evidence
  records into a read-only map without changing task execution semantics. Map
  missing evidence explicitly as `unavailable` and never infer a PASS state.

- [ ] **Step 4: Add API routes and local event replay**

  Validate project identity and revision, return the current snapshot, and
  expose ordered lifecycle events suitable for browser polling or streaming.

- [ ] **Step 5: Run project-map tests**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/project_view apps/eeee/tests/api/test_project_view_routes.py`

  Expected: all project-map and route tests pass.

- [ ] **Step 6: Commit**

  `git add apps/eeee/app/project_view apps/eeee/app/harness apps/eeee/app/api/routes.py apps/eeee/app/main.py apps/eeee/tests/project_view apps/eeee/tests/api/test_project_view_routes.py && git commit -m "feat: expose ISEOL project organization map"`

### Task 5: Unified ClaimLatch, deterministic QA, release, and memory gates

**Files:**
- Create: `apps/eeee/app/trust/pipeline.py`
- Modify: `apps/eeee/app/trust/gate.py`
- Modify: `apps/eeee/app/integrations/claimlatch_audit.py`
- Modify: `apps/eeee/app/execution/verifier.py`
- Modify: `apps/eeee/app/memory/pipeline.py`
- Modify: `apps/eeee/app/api/service.py`
- Test: `apps/eeee/tests/trust/test_pipeline.py`
- Modify: `apps/eeee/tests/trust/test_gate.py`
- Modify: `apps/eeee/tests/harness/test_verifier.py`
- Modify: `apps/eeee/tests/memory/test_outcome_pipeline.py`

**Interfaces:**
- Produces `TrustPipeline.verify_claim(envelope)`,
  `verify_action(envelope)`, `release_gate(envelope, qa_report)`, and
  `memory_promotion_gate(outcome, envelope, qa_report)`.
- Every method returns a structured decision with decision, reason, project
  revision, ClaimLatch receipt, QA report reference, and evidence IDs.

- [ ] **Step 1: Write failing trust-pipeline tests**

  Pin PASS, WARN, and BLOCK decisions for ClaimLatch unavailable, stale
  revision, deterministic QA failure, mismatched project identity, and valid
  evidence. Assert release and memory promotion cannot succeed on a missing or
  non-PASS trust result.

- [ ] **Step 2: Run trust tests to verify they fail**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/trust/test_pipeline.py`

  Expected: FAIL because the unified pipeline does not exist.

- [ ] **Step 3: Implement the trust pipeline**

  Compose the existing TrustGate, ClaimLatch audit store, deterministic
  verifier, and memory compiler behind one revision-aware service. Keep local
  planning inspectable when ClaimLatch is unavailable, but block external
  action, release, and memory promotion according to the approved policy.

- [ ] **Step 4: Integrate the pipeline with API flow and memory promotion**

  Replace scattered success decisions with the structured pipeline decision,
  preserve existing response shapes, and persist all receipts/evidence on the
  execution envelope.

- [ ] **Step 5: Run trust, verifier, and memory regressions**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/trust apps/eeee/tests/harness/test_verifier.py apps/eeee/tests/memory/test_outcome_pipeline.py`

  Expected: all focused and existing trust regressions pass.

- [ ] **Step 6: Commit**

  `git add apps/eeee/app/trust apps/eeee/app/integrations/claimlatch_audit.py apps/eeee/app/execution/verifier.py apps/eeee/app/memory/pipeline.py apps/eeee/app/api/service.py apps/eeee/tests/trust apps/eeee/tests/harness/test_verifier.py apps/eeee/tests/memory/test_outcome_pipeline.py && git commit -m "feat: unify ClaimLatch QA and release gates"`

### Task 6: Lightweight Plugin Host, manifest validation, and fake plugin fixture

**Files:**
- Create: `apps/eeee/app/plugins/__init__.py`
- Create: `apps/eeee/app/plugins/models.py`
- Create: `apps/eeee/app/plugins/manifest.py`
- Create: `apps/eeee/app/plugins/host.py`
- Create: `apps/eeee/app/plugins/protocol.py`
- Modify: `apps/eeee/app/main.py`
- Modify: `apps/eeee/app/api/routes.py`
- Test: `apps/eeee/tests/plugins/test_manifest.py`
- Test: `apps/eeee/tests/plugins/test_host.py`
- Test: `apps/eeee/tests/plugins/fixtures/echo_plugin.py`
- Test: `apps/eeee/tests/plugins/fixtures/echo-plugin.json`

**Interfaces:**
- Produces strict `PluginManifest`, `PluginAction`, `PluginPermission`,
  `PluginStatus`, and `PluginHealth` models.
- Produces `PluginHost.discover(source)`, `register(manifest)`,
  `connect(plugin_id, approval)`, `invoke(plugin_id, action, input)`,
  `health(plugin_id)`, `disconnect(plugin_id)`, and
  `remove(plugin_id)`.
- Adds local API routes for listing manifests, inspecting permissions,
  approving/connecting, invoking, health-checking, disconnecting, and removing
  plugins. Every action returns an `ExecutionEnvelope`.

- [ ] **Step 1: Write failing manifest and permission tests**

  Assert valid manifest parsing, protocol-version checks, malformed schema
  rejection, unknown side-effect rejection, permission display, and refusal to
  register a manifest that requests disallowed scopes.

- [ ] **Step 2: Run manifest tests to verify they fail**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/plugins/test_manifest.py`

  Expected: FAIL because the plugin contract models do not exist.

- [ ] **Step 3: Implement manifest validation and registry integration**

  Validate plugin metadata as untrusted input, store only the manifest and
  audit state, and register declared capabilities only after approval and a
  successful health check. Do not import plugin implementation modules.

- [ ] **Step 4: Write failing host lifecycle tests with the echo fixture**

  Pin discover → inspect → approve → register → health-check → invoke →
  disconnect → remove. Assert denied approval, missing plugin, malformed
  output, and process failure produce truthful envelopes and do not call
  ClaimLatch-protected external actions.

- [ ] **Step 5: Implement the versioned local JSON protocol and host**

  Use a subprocess fixture for isolation, request/response correlation IDs,
  bounded output, health timeout, and explicit shutdown. Keep transport details
  behind `PluginTransport` so a future JSON-RPC or MCP transport can implement
  the same contract.

- [ ] **Step 6: Add plugin lifecycle API routes and application wiring**

  Mount plugin routes under `/api/plugins`, connect them to the kernel registry,
  permission policy, execution store, local event bus, and TrustPipeline.

- [ ] **Step 7: Run plugin tests**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/plugins`

  Expected: all manifest, permission, lifecycle, health, process-failure, and
  envelope tests pass.

- [ ] **Step 8: Commit**

  `git add apps/eeee/app/plugins apps/eeee/app/main.py apps/eeee/app/api/routes.py apps/eeee/tests/plugins && git commit -m "feat: add isolated local plugin host"`

### Task 7: Assistant surface, project-map visualization, and end-to-end body flow

**Files:**
- Modify: `apps/eeee/app/desktop/window.py`
- Modify: `apps/eeee/app/desktop/client.py`
- Modify: `apps/eeee/app/static/index.html`
- Modify: `apps/eeee/app/static/app.js`
- Modify: `apps/eeee/app/static/styles.css`
- Test: `apps/eeee/tests/desktop/test_window.py`
- Test: `apps/eeee/tests/desktop/test_client.py`
- Create: `apps/eeee/tests/ui_project_map.js`
- Create: `apps/eeee/tests/e2e/test_core_project_flow.py`

**Interfaces:**
- Desktop client consumes kernel, plugin, and project-map APIs and exposes
  capability cards plus `open_project(project_id)`.
- Browser view consumes `GET /api/projects/{project_id}/map` and its event
  cursor API to render nodes and edges.
- The UI displays Korean by default with English selection and shows statuses,
  current node, commits, ClaimLatch, QA, evidence, errors, and retries.

- [ ] **Step 1: Write failing UI and end-to-end tests**

  Assert capability cards, the one-sentence project request, automatic
  navigation to the project map, visual node status classes, selected-node
  details, zero-plugin startup, and a seeded Todo-style request producing a
  project ID and map snapshot.

- [ ] **Step 2: Run UI tests to verify they fail**

  Run: `node --test apps/eeee/tests/ui_project_map.js` and
  `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/e2e/test_core_project_flow.py`

  Expected: FAIL because the capability launcher and project-map UI are not
  implemented.

- [ ] **Step 3: Add capability launcher and project creation flow**

  Replace the primary Desktop interaction with capability cards and one
  natural-language project input while retaining compatibility controls behind
  the project view. On successful project creation, open the project map URL
  with the project ID and language.

- [ ] **Step 4: Implement the project organization map view**

  Render a pannable, zoomable, depth-styled node graph from the map snapshot.
  Highlight active nodes, distinguish completed/waiting/blocked/failed nodes,
  and open a detail panel for commits, changed files, trust receipts, QA,
  troubleshooting, and evidence. Use event cursors to update without full-page
  flashing.

- [ ] **Step 5: Add plugin cards and connection flow**

  Show available/installed plugin manifests in the assistant surface. A click
  or natural-language request opens the permission explanation, approval,
  connection, health, and failure states without exposing secrets.

- [ ] **Step 6: Run UI and end-to-end tests**

  Run: `node --test apps/eeee/tests/ui_project_map.js`; then
  `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/e2e/test_core_project_flow.py apps/eeee/tests/desktop`; then
  `node --check apps/eeee/app/static/app.js`.

  Expected: all UI, desktop, and zero-plugin project-flow tests pass.

- [ ] **Step 7: Commit**

  `git add apps/eeee/app/desktop apps/eeee/app/static apps/eeee/tests/desktop apps/eeee/tests/ui_project_map.js apps/eeee/tests/e2e/test_core_project_flow.py && git commit -m "feat: add assistant launcher and project map"`

### Task 8: Full regression, local packaging, and body documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/operations/local-runtime.md`
- Modify: `scripts/verify-all.ps1` (only if new body checks are missing)
- Test: `apps/eeee/tests/test_core_contract.py`

**Interfaces:**
- Documents the body installation and one-sentence project flow, plugin
  connection flow, trust behavior, and project-map usage.
- Adds a release contract test that verifies optional provider packages are not
  required by the core build and that the ClaimLatch profile is
  `claimlatch-v0.2.0`.

- [ ] **Step 1: Write failing release-contract tests**

  Assert the clean core starts with no plugin registrations, the required
  capability set is present, the plugin host is available, and optional
  provider implementation imports are not required.

- [ ] **Step 2: Implement documentation and release checks**

  Document `Todo 앱 만들어줘`, project-map navigation, plugin connection by
  EEEE, approval/permission behavior, local storage paths, and troubleshooting
  commands. Keep optional plugin repositories outside the core quick start.

- [ ] **Step 3: Run the complete verification suite**

  Run:

  ```powershell
  C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests
  node --check apps/eeee/app/static/app.js
  node --test apps/eeee/tests/ui_project_map.js
  .\scripts\verify-all.ps1 -Full
  .\scripts\build-desktop.ps1 -PythonPath C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe
  ```

  Expected: all Python/Node tests, repository verification, and packaged GUI
  import self-test pass. The packaged GUI must launch without the Qt ICU DLL
  collision fixed in the earlier desktop build.

- [ ] **Step 4: Commit**

  `git add README.md docs/operations/local-runtime.md scripts/verify-all.ps1 apps/eeee/tests/test_core_contract.py && git commit -m "test: verify the local EEEE core body"`

