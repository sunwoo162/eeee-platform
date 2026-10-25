# Personal LLM Desktop Autostart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax to track progress.

**Goal:** Start the local personal LLM automatically when the EEEE cat desktop starts, while reusing an existing service and stopping only processes EEEE owns.

**Architecture:** Extend `EmbeddedApiRuntime` with a loopback-only personal LLM child-process lifecycle alongside the existing Ollama lifecycle. Add explicit settings for autostart, project root, executable, and startup timeout; health-check before spawning and tolerate startup failure so the cat UI remains usable.

**Tech Stack:** Python 3.12, Pydantic Settings, subprocess, urllib, pytest, PowerShell launcher.

**Spec:** `docs/superpowers/specs/2026-10-25-personal-llm-desktop-autostart-design.ko.md`

## Global Constraints

- Only loopback personal LLM URLs may be auto-started.
- Existing healthy personal LLM processes must be reused and never terminated by EEEE.
- Child startup failure must not prevent the EEEE desktop UI from opening.
- No Windows global startup registration is added.
- Use TDD: each runtime behavior has a failing test before production code.

## Review Focus

- An already-running service must not be duplicated or killed: cover healthy-reuse and owned-child cleanup tests.
- A missing executable/project must not crash EEEE desktop startup: cover graceful skip.
- A non-loopback URL must not trigger process management: cover URL boundary.
- Both `personal_llm` and `auto` provider modes should start the service: cover provider selection.
- Startup timeout/child exit should leave EEEE able to start: cover non-fatal readiness failure.

### Task 1: Runtime settings and personal LLM child lifecycle

**Files:**
- Modify: `apps/eeee/app/config.py`
- Modify: `apps/eeee/app/desktop/runtime.py`
- Test: `apps/eeee/tests/desktop/test_runtime.py`

**Interfaces:**
- Settings produce `personal_llm_autostart`, `personal_llm_project_root`,
  `personal_llm_executable`, and `personal_llm_startup_timeout_seconds`.
- `EmbeddedApiRuntime._ensure_personal_llm_service()` owns only a process it
  started and is called by `_ensure_local_model_service()` during desktop boot.

- [ ] Write failing tests for personal provider startup, `auto` startup, healthy reuse, non-loopback skip, and owned-child cleanup.
- [ ] Run the focused tests and confirm they fail because the settings/lifecycle are absent.
- [ ] Add settings with environment aliases and positive timeout validation.
- [ ] Implement loopback health detection, project/executable resolution, non-fatal child startup, readiness wait, and owned-process cleanup.
- [ ] Run the focused runtime tests and confirm they pass.
- [ ] Commit as `feat: auto-start personal llm with desktop`.

### Task 2: Operator documentation and local verification

**Files:**
- Modify: `apps/eeee/.env.example`
- Modify: `apps/eeee/README.md`
- Modify: `docs/operations/local-runtime.md`

- [ ] Document defaults and override variables for automatic startup.
- [ ] Run the focused integration tests and the repository core verification.
- [ ] Commit as `docs: document personal llm desktop autostart`.
