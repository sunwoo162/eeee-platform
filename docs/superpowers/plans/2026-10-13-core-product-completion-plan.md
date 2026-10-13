# EEEE Core Product Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the EEEE desktop assistant core while explicitly excluding development of new external plugins/connectors.

**Architecture:** Keep EEEE as the local FastAPI/SQLite authority, use the existing desktop supervisor and ISEOL bridge as execution boundaries, and require durable evidence plus ClaimLatch/QA gates before release or memory promotion. Existing plugin catalog and connection contracts remain available but are not expanded into new provider implementations.

**Tech Stack:** Python 3.12, FastAPI, SQLite, PySide6, PyInstaller, TypeScript/Node.js ISEOL bridge, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-eeee-desktop-assistant-product-design.md`, `docs/superpowers/specs/2026-10-06-eeee-personal-assistant-platform-design.md`.

## Global Constraints

- Preserve existing user changes and untracked test artifacts; never reset or broad-delete.
- General conversation, local actions, project work, and plugin work must be distinct routes.
- ChatGPT Web may provide reasoning, but local runtime owns files, commands, and side effects.
- No success, release, or memory promotion without current-revision evidence and ClaimLatch/QA gates.
- New external plugin/provider implementation is out of scope for this plan.
- Every behavior change follows a failing test, minimal implementation, green regression suite, and a focused commit.

## Review Focus

- A desktop/API restart during a long project run must resume from the last durable checkpoint.
- A slow or unavailable reasoning provider must produce a visible blocked/retry state, never fake success.
- A stale execution revision or duplicate retry must not mutate the wrong project or duplicate side effects.
- A passing-looking project with missing evidence, failed QA, or unavailable ClaimLatch must not release or promote memory.
- A packaged Windows launch must avoid duplicate helper windows and provide actionable recovery for port/bridge failures.

### Task 1: Establish the core completion baseline

**Files:**
- Modify: `docs/operations/local-runtime.md`
- Modify: `docs/operations/release-checklist.md` (if present)
- Test: `apps/eeee/tests/e2e/` and existing core test modules

- [ ] Run the complete EEEE Python suite and package self-test from a clean feature branch.
- [ ] Map each Session 1–9 requirement to an existing test or a missing regression test.
- [ ] Record only confirmed gaps in this plan and keep unrelated dirty artifacts untouched.

### Task 2: Durable execution lifecycle and recovery

**Files:**
- Modify: `apps/eeee/app/assistant/background.py`
- Modify: `apps/eeee/app/assistant/service.py`
- Modify: `apps/eeee/app/runtime/store.py`
- Modify: `apps/eeee/app/api/routes.py`
- Test: `apps/eeee/tests/assistant/test_background_supervisor.py`
- Test: `apps/eeee/tests/api/test_assistant_jobs_api.py`
- Test: `apps/eeee/tests/runtime/test_store.py`

- [ ] Add failing tests for checkpoint persistence, restart recovery, lease expiry, cancellation, and idempotent retry.
- [ ] Implement the smallest durable supervisor/state transition changes needed by those tests.
- [ ] Expose accepted execution IDs and recovery state without holding an HTTP request open.
- [ ] Verify the full assistant and API suites.

### Task 3: Assistant routing and provider isolation

**Files:**
- Modify: `apps/eeee/app/assistant/router.py`
- Modify: `apps/eeee/app/assistant/service.py`
- Modify: `apps/eeee/app/agent/hybrid_runtime.py` or the existing provider selector
- Test: `apps/eeee/tests/assistant/test_router.py`
- Test: `apps/eeee/tests/agent/test_hybrid_runtime.py`
- Test: `apps/eeee/tests/api/test_assistant_routes.py`

- [ ] Pin tests for ordinary conversation, memory questions, local actions, project requests, and unavailable-provider responses.
- [ ] Ensure project execution is selected only for explicit project intent and never for ordinary chat.
- [ ] Ensure provider output cannot directly execute a side effect and errors become blocked/retryable user state.
- [ ] Verify provider/session identity and conversation history are scoped correctly.

### Task 4: ISEOL handoff and real progress view

**Files:**
- Modify: `apps/eeee/app/project_runtime/iseol_bridge.py`
- Modify: `apps/eeee/app/project_runtime/runner.py` or the current runner module
- Modify: `apps/eeee/app/project_view/` and `apps/eeee/app/api/routes.py`
- Test: `apps/eeee/tests/project_runtime/test_iseol_bridge.py`
- Test: `apps/eeee/tests/planning/test_handoff_integration.py`
- Test: `apps/eeee/tests/project_view/`
- Test: `apps/eeee/tests/api/test_project_view_routes.py`

- [ ] Add failing tests for ordered handoff, blocked dependencies, stale revisions, retry/replan, and event-cursor refresh.
- [ ] Make the progress map consume durable events and show current agent, commit, changed files, evidence, and next action.
- [ ] Add pause/resume/cancel/retry behavior only where the existing execution contract supports it.
- [ ] Verify the map survives refresh and process restart.

### Task 5: ClaimLatch, QA, release, and memory gates

**Files:**
- Modify: `apps/eeee/app/trust/gate.py`
- Modify: `apps/eeee/app/trust/pipeline.py`
- Modify: `apps/eeee/app/project_runtime/evidence.py`
- Modify: `apps/eeee/app/release/` if present
- Test: `apps/eeee/tests/trust/`
- Test: `apps/eeee/tests/integrations/`
- Test: `apps/eeee/tests/release/`

- [ ] Add failing tests for missing evidence, stale revision, ClaimLatch unavailable, QA failure, and release manifest mismatch.
- [ ] Enforce fail-closed release and memory promotion behavior.
- [ ] Persist redacted evidence and receipts with the same project/revision/run identifiers.
- [ ] Verify the release/security suites and the end-to-end todo flow.

### Task 6: Packaging, single-instance behavior, and recovery UX

**Files:**
- Modify: `apps/eeee/app/desktop/runtime.py`
- Modify: `apps/eeee/app/desktop/session.py`
- Modify: `scripts/build-desktop.ps1`
- Modify: `scripts/verify-all.ps1`
- Modify: `docs/operations/local-runtime.md`
- Test: `apps/eeee/tests/desktop/`
- Test: `apps/eeee/tests/test_runtime_entrypoint.py`

- [ ] Add failing tests for duplicate launch, helper-window suppression, port conflict, bridge timeout, and clean restart.
- [ ] Implement single-instance/recovery behavior without hiding failures.
- [ ] Build the Windows executable and run packaged self-test plus the documented verification command.
- [ ] Update the operator runbook with exact recovery commands and logs.

### Task 7: Final integration and delivery

- [ ] Run the full Python and TypeScript suites, compile checks, encoding check, package build, and packaged self-test.
- [ ] Review the diff for secrets, generated artifacts, and unrelated changes.
- [ ] Split commits by independently reviewable subsystem, push a PR, merge only after checks are green, and remove only the merged branch.
- [ ] Verify remote `main`, running packaged executable, and preserved user worktrees.
