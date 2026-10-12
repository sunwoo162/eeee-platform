# EEEE Core Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the non-plugin EEEE core so real assistant requests have durable lifecycle control, trustworthy memory, release-gated project results, a usable control center, and reproducible verification.

**Architecture:** Keep the local-first Python/FastAPI/SQLite architecture. The assistant supervisor remains the durable source of truth for background work; memory remains a separate promoted-record store; release manifests remain fail-closed and revision-bound. The desktop Workspace consumes the same local API and never becomes a second state store.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, PySide6 desktop shell, pytest, existing deterministic verifier and ClaimLatch adapter.

**Spec:** `docs/superpowers/specs/2026-10-08-eeee-desktop-assistant-product-design.md`

## Global Constraints

- EEEE is the user's general desktop assistant; it is not a project-only interface.
- Local Desktop and SQLite remain the default source of truth.
- Background work must survive UI closure and resume after restart.
- No result is reported as complete without files, tests, evidence, ClaimLatch, and a consistent release manifest.
- New optional plugin capabilities are explicitly out of scope for this plan.
- Existing untracked pytest artifacts are user-owned test evidence and must not be deleted or staged.
- Every behavior change follows RED → GREEN → full relevant suite verification.

## Review Focus

- A queued/running job must not be lost or falsely completed after shutdown/restart.
- A user must be able to inspect, pause, resume, cancel, and retry work without corrupting the durable record.
- Automatic memory capture must not silently promote unverified project claims or make deletion impossible.
- A release must fail when an artifact is missing, non-UTF-8, stale, or lacks evidence even if an agent says it completed.
- The Workspace must show the same job, memory, plugin-state, and verification truth as the API without developer-only placeholder copy.

### Task 1: Durable assistant job lifecycle

**Files:**
- Modify: `apps/eeee/app/assistant/background.py`
- Modify: `apps/eeee/app/assistant/service.py`
- Modify: `apps/eeee/app/api/routes.py`
- Test: `apps/eeee/tests/assistant/test_background_supervisor.py`
- Test: `apps/eeee/tests/api/test_assistant_jobs_api.py`

**Interfaces:**
- Produces `list_jobs()`, `pause(job_id)`, `resume(job_id, operation_factory)`, `cancel(job_id)`, and `retry(job_id, operation_factory)` with durable status transitions.
- API exposes list and lifecycle endpoints while preserving the existing `GET /api/assistant/jobs/{job_id}` contract.

- [ ] Write failing tests for lifecycle transitions, idempotency, invalid transitions, and persisted input after restart.
- [ ] Run the focused tests and confirm they fail for the missing lifecycle behavior.
- [ ] Implement the smallest SQLite-backed transition layer and service/API adapters.
- [ ] Run focused tests, then the assistant/API regression suites.
- [ ] Commit as `feat: add durable assistant job lifecycle`.

### Task 2: Memory inspection and safe user controls

**Files:**
- Modify: `apps/eeee/app/memory/store.py`
- Modify: `apps/eeee/app/api/routes.py`
- Test: `apps/eeee/tests/memory/test_memory_store.py`
- Test: `apps/eeee/tests/api/test_memory_api.py`

**Interfaces:**
- Produces scoped memory listing, explicit revoke/delete operations, and a status-safe memory detail response.
- Existing candidate/promotion/provenance semantics remain unchanged.

- [ ] Write failing tests for listing by status/scope, revocation, deletion, and refusal to delete an already superseded record incorrectly.
- [ ] Run the focused tests and confirm the expected missing-operation failures.
- [ ] Implement store methods and API routes with audit events and no raw secret exposure.
- [ ] Run memory and API regression suites.
- [ ] Commit as `feat: add safe memory inspection controls`.

### Task 3: Fail-closed release artifact verification

**Files:**
- Modify: `apps/eeee/app/release/manifest.py`
- Modify: `apps/eeee/app/project_runtime/evidence.py`
- Test: `apps/eeee/tests/release/test_release_manifest_gate.py`
- Test: `apps/eeee/tests/project_runtime/test_project_runtime_provisioner.py`

**Interfaces:**
- `build_release_manifest` verifies artifact paths are inside the declared workspace, exist, are UTF-8 where textual, and have evidence bound to the same project revision.
- Existing PASS/BLOCK behavior and manifest schema remain backward compatible for valid artifacts.

- [ ] Write failing tests for missing artifacts, path escape, invalid UTF-8, and evidence belonging to a stale revision.
- [ ] Run the focused release tests and confirm they fail for the new checks.
- [ ] Implement deterministic artifact validation without invoking an unrestricted command runner.
- [ ] Run release, evidence, project-runtime, and end-to-end generation suites.
- [ ] Commit as `fix: harden release artifact verification`.

### Task 4: EEEE Workspace control-center data and UI

**Files:**
- Modify: `apps/eeee/app/api/routes.py`
- Modify: `apps/eeee/app/desktop/workspace.py`
- Modify: `apps/eeee/app/static/index.html`
- Modify: `apps/eeee/app/static/app.js`
- Modify: `apps/eeee/app/static/styles.css`
- Test: `apps/eeee/tests/desktop/test_workspace.py`
- Test: `apps/eeee/tests/api/test_desktop_routes.py`
- Test: `apps/eeee/tests/design/test_api.py`

**Interfaces:**
- Workspace snapshot includes current jobs, recent results, memory summary, plugin connection states, and verification/release status.
- UI labels describe EEEE actions in user language and never show the old development-only placeholder as the empty state.

- [ ] Write failing API/UI contract tests for the complete control-center snapshot and empty state.
- [ ] Run them and confirm the missing fields/labels.
- [ ] Implement one shared snapshot shape consumed by PySide6 and browser control plane.
- [ ] Run desktop/API/design regression tests and a browser smoke test.
- [ ] Commit as `feat: complete eeee workspace control center`.

### Task 5: Operational hardening, documentation, and acceptance proof

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/integration-plan.md`
- Modify: `README.md`
- Create: `scripts/verify-core-product.ps1`
- Test: `apps/eeee/tests/test_release_docs.py`
- Test: `apps/eeee/tests/e2e/test_core_project_flow.py`

**Interfaces:**
- The verification script runs encoding checks, Python tests, core E2E, and reports actionable failures without requiring optional plugins.
- Documentation reflects the current ClaimLatch integration and clearly separates local-complete from externally-configured deployment behavior.

- [ ] Write failing documentation/script contract tests for stale ClaimLatch statements and missing verification steps.
- [ ] Run them and confirm the stale-documentation failures.
- [ ] Update docs and add the repeatable core verification command.
- [ ] Run the complete Python suite, core E2E, build/package checks, and the verification script.
- [ ] Commit as `chore: document and verify eeee core release`.

## Final Acceptance

- [ ] `안녕` receives a real local conversational response without selecting a project plugin.
- [ ] `todo 앱 만들어줘` creates a durable background job and a project only after the core route accepts it.
- [ ] A restarted supervisor resumes the same job from persisted input.
- [ ] Workspace and API show the same job/project/release truth.
- [ ] Memory survives restart, remains inspectable, and unverified candidates are not silently promoted.
- [ ] Missing/stale/non-UTF-8 artifacts block release.
- [ ] Optional plugins are not required for the core path.
- [ ] Full test and verification output is captured before any completion claim.
