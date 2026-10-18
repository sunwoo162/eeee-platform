# EEEE Post-Live Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the remaining EEEE acceptance gaps after the live Web GPT bridge verification without changing Web GPT as the active brain or pretending that user-specific plugin credentials are connected.

**Architecture:** Keep EEEE Core as the local durable coordinator and the ISEOL browser bridge as the Web GPT transport. Validate the existing packaged Desktop boundary and all repository-local plugin lifecycle contracts, then record environment-gated connector authentication separately.

**Tech Stack:** Python 3.12, FastAPI, SQLite, PySide6, PyInstaller, TypeScript/Node.js, pytest, npm, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-15-eeee-core-redesign-design.md`, `docs/superpowers/verification/2026-10-15-eeee-v1-acceptance.md`

## Global Constraints

- Web GPT remains the default EEEE provider.
- Ollama must never auto-start or silently receive a Web GPT request; it is explicit legacy/debug mode only.
- Optional plugin connectors remain opt-in and must fail closed when installation, permission, or authentication is absent.
- No user passwords, cookies, tokens, or external account credentials are automated or stored in the repository.
- Every completion claim requires fresh command output and a clean diff.

## Review Focus

- Packaged Desktop must start its embedded API and exit cleanly in `--self-test` mode.
- Packaged GUI import must not require a live browser, Node process, or plugin credentials.
- Plugin catalog and lifecycle must distinguish install, connect, health, and invoke failures.
- Unified verification must run from the documented working directories and not rely on hidden environment files.
- Acceptance records must distinguish live Web GPT evidence from unverified external connector authentication.

### Task 1: Verify and harden the Windows Desktop package

**Files:**
- Modify only if the build exposes a defect: `scripts/build-desktop.ps1`, `apps/desktop/gleave-desktop.spec`, `apps/eeee/app/desktop/`
- Test: packaged `GleaveDesktop.exe --self-test` and `--gui-self-test`

**Interfaces:**
- Consumes `apps/eeee/app/desktop/__main__.py` and `apps/desktop/gleave-desktop.spec`.
- Produces a verified `build/desktop/GleaveDesktop.exe` without committing generated artifacts.

- [ ] Run the documented build script with the installed Python/PyInstaller environment.
- [ ] If it fails, add a focused regression test or minimal packaging fix, rerun the failing command, then rerun both packaged self-tests.
- [ ] Confirm generated build output remains ignored and no secret/config file is bundled.

### Task 2: Run the complete cross-runtime verification

**Files:**
- Modify only if verification exposes a defect: affected source and test files.
- Test: `scripts/verify-all.ps1 -Full`

**Interfaces:**
- Consumes EEEE, ISEOL, ClaimLatch adapter, and Mobile test contracts.
- Produces fresh cross-runtime evidence for the acceptance record.

- [ ] Run the unified verification from the repository root.
- [ ] Resolve only real regressions; preserve the Web GPT/Ollama provider policy.
- [ ] Run the EEEE full suite again from `apps/eeee` if the unified command changes code.

### Task 3: Verify optional plugin lifecycle boundaries

**Files:**
- Inspect `apps/eeee/app/plugins/`, `apps/eeee/tests/plugins/`, `docs/operations/plugin-connectors.md`.
- Modify only if a repository-local lifecycle contract is missing.

**Interfaces:**
- Consumes catalog, OAuth broker, connector platform, and capability permission contracts.
- Produces a truthful install/connect/health/invoke status without requiring a real external account.

- [ ] Run focused plugin catalog, OAuth, platform, capability, and API tests.
- [ ] Verify uninstalled or unauthenticated connectors stay non-routable and redact secrets.
- [ ] Leave provider-specific OAuth login as a documented manual gate rather than fabricating a connected state.

### Task 4: Record final evidence and review the branch

**Files:**
- Modify `docs/superpowers/verification/2026-10-15-eeee-v1-acceptance.md`.
- Modify this plan ledger only in the ignored `.superpowers/sdd/` workspace.

- [ ] Record exact package, unified verification, plugin, and live Web GPT results.
- [ ] Run `git diff --check`, inspect generated artifacts, and confirm `git status` is clean after commits.
- [ ] Do not mark Ollama live generation or external plugin account authentication as complete unless fresh evidence exists.

