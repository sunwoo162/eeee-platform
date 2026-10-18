# EEEE Release Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the already implemented EEEE core, ISEOL runtime, desktop shell, and plugin host into a verified, reviewable, commit-ready branch without claiming unverified external account behavior.

**Architecture:** Keep EEEE Core as the local durable coordinator, Web GPT as the default conversation provider, ISEOL as the built-in project execution capability, and optional connectors behind the isolated plugin/OAuth boundary. Existing uncommitted work is preserved and classified into vertical commits; only observed regressions receive code changes.

**Tech Stack:** Python 3.12, FastAPI, SQLite, PySide6, PyInstaller, TypeScript/Node.js, pytest, PowerShell, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-16-iseol-project-execution-design.md`, `docs/superpowers/specs/2026-10-15-eeee-core-redesign-design.md`

## Global Constraints

- Web GPT remains the default EEEE provider; Ollama remains explicit legacy/debug mode.
- Missing, denied, disconnected, or failed plugin operations must never be reported as successful.
- User credentials, cookies, tokens, generated executables, databases, and local runtime state must not enter Git.
- Native Python ISEOL graph execution remains authoritative; compatibility adapters must not become a second planner.
- Every fix must have a regression test written and observed failing before production code is changed.
- Commit and PR boundaries must be vertical and reviewable; do not squash unrelated subsystems into one opaque commit.

## Review Focus

- A terminal assistant response must be clickable to start a fresh input session rather than merely extending its hide timer.
- Dynamic bubble text must remain fully visible for one-line, multi-line, Korean, long, error, and in-progress states without a fixed body height.
- A restarted process must retain local configuration, conversation state, and provider selection without silently switching providers.
- A connector must distinguish install, OAuth, permission, health, and invoke failures and redact credentials in all surfaced state.
- A natural-language project run must stop with truthful evidence when a required extension or external provider is unavailable.

---

### Task 1: Establish the release baseline and classify the existing worktree

**Files:**
- Read: existing branch, `git diff`, existing verification records, and plan ledgers.
- Modify: this plan's ignored ledger only.
- Test: documented EEEE, ISEOL, desktop, plugin, and cross-runtime verification commands.

**Interfaces:**
- Consumes the current isolated worktree on `codex/eeee-main-sync` and the existing uncommitted implementation.
- Produces a file-level classification for the later vertical commits and fresh baseline evidence.

- [ ] Verify the current checkout is the existing isolated EEEE worktree, not the ClaimLatch source checkout.
- [ ] Run focused tests for assistant, memory, desktop, ISEOL, project runtime, plugins, and E2E before changing production code.
- [ ] Record any failures by test name and classify each as regression, environment gate, or stale expectation.
- [ ] Do not change source code in this task unless a test command itself is broken by the repository state.

### Task 2: Fix observed core, desktop, and ISEOL regressions with TDD

**Files:**
- Modify only the production file named by a failing regression.
- Test: the smallest existing or new regression test beside the affected subsystem.

**Interfaces:**
- Consumes the EEEE conversation/provider, desktop presentation, memory, ISEOL orchestration, and project-runtime contracts.
- Produces behavior that remains compatible with the current public API and persisted local state.

- [ ] For each actual failure, write or refine one behavior-level regression test and run it to the expected RED result.
- [ ] Implement the smallest fix, then run the regression test GREEN and the affected subsystem suite.
- [ ] Re-run the full Python suite after the last fix; do not hide warnings or environment-gated failures.

### Task 3: Verify plugin lifecycle and provider boundaries

**Files:**
- Inspect and modify only `apps/eeee/app/plugins/`, `apps/eeee/app/assistant/`, `apps/eeee/app/kernel/`, and their tests when a lifecycle defect is observed.
- Update `docs/operations/plugin-connectors.md` only when runtime behavior and documentation disagree.

**Interfaces:**
- Consumes catalog, install, OAuth, permission, health, connector, and capability-routing contracts.
- Produces truthful local plugin state and a clear manual gate for external account authentication.

- [ ] Run focused catalog, OAuth, provider, protocol, platform, capability, and route tests.
- [ ] Verify uninstalled, unauthenticated, denied, unhealthy, and failed-invoke states remain non-routable and secret-free.
- [ ] Verify Web GPT remains the active default and Ollama is not selected as an implicit fallback.
- [ ] Run only read-only or already-authorized connector health checks; do not send external mail or create external data without a new explicit request.

### Task 4: Package, document, commit, and prepare the review boundary

**Files:**
- Modify: acceptance/verification documentation and only source files proven necessary by Tasks 1–3.
- Create: logical Git commits for core/runtime, desktop, ISEOL, and plugin lifecycle changes as the diff supports.

**Interfaces:**
- Consumes fresh test, package, and static verification evidence from Tasks 1–3.
- Produces a clean, reviewable branch and Korean PR-ready summary; generated artifacts remain ignored.

- [ ] Run the packaged Desktop build and both packaged self-tests.
- [ ] Run the complete cross-runtime verification and `git diff --check`.
- [ ] Update the acceptance record with exact fresh results and explicit environment-gated items.
- [ ] Inspect the final diff for secrets, generated files, accidental unrelated changes, and encoding damage.
- [ ] Commit the verified changes with vertical Korean-facing PR descriptions and keep the branch available for review.
