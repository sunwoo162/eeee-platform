# Gleave Core Product Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the local Gleave product execute real ISEOL work, verify generated web projects with browser E2E evidence, route general requests naturally, and leave a reproducible clean verification workflow.

**Architecture:** EEEE remains the local control plane and user-facing assistant. ISEOL owns project decomposition and specialist execution; each specialist must emit workspace/evidence records consumed by QA and ClaimLatch. Optional connectors remain outside the core and are reported as unavailable until explicitly configured.

**Tech Stack:** Python 3.12, FastAPI, PySide6, SQLite, TypeScript/Node.js, Playwright, PyInstaller, local ChatGPT Web bridge.

**Spec:** `docs/architecture/eeee-platform.md` and the current EEEE/ISEOL/ClaimLatch product requirements.

## Global Constraints

- No hosted EEEE server is required for local operation.
- No external side effect may be reported as completed without evidence.
- ClaimLatch and project revision identity must be preserved through every child execution.
- Korean is the default UI language; English remains selectable.
- Optional plugins must not be bundled into the core execution path.
- A project is releasable only when implementation, QA, and ClaimLatch agree on the same revision.

## Review Focus

- A generated agent graph must execute specialist work when the configured runtime is available, and report blocked—not completed—when it is not.
- Browser E2E must perform real user actions rather than inspect markdown tokens.
- Web projects must not claim production authentication or deployment while running in demo mode.
- General conversation must not be misrouted to project execution.
- Root and package-level verification commands must be reproducible without hidden `PYTHONPATH` setup.

---

### Task 1: Make specialist-agent execution explicit and evidence-backed

**Files:**
- Modify: `apps/eeee/app/main.py`, `apps/eeee/app/kernel/capabilities.py`
- Modify: `apps/eeee/app/project_runtime/iseol_bridge.py`
- Test: `apps/eeee/tests/project_runtime/` and `apps/eeee/tests/assistant/`

- [ ] Add RED tests proving the project path returns BLOCKED when an agent graph contains executable specialists but no runtime, and COMPLETED only after the runtime reports completed handoffs.
- [ ] Implement an explicit runtime availability decision and serialize specialist reports into `execution-plan.json`, `PROJECT_LOG.md`, and the parent envelope.
- [ ] Keep deterministic Todo/Web runners available as scaffolding verification, but do not treat them as specialist-agent completion evidence.
- [ ] Run focused Python tests and the packaged desktop self-test.

### Task 2: Add real browser E2E evidence to web project QA

**Files:**
- Modify: `apps/eeee/app/project_runtime/web_runner.py`
- Create/Modify: `apps/eeee/app/project_runtime/browser_e2e.py`
- Test: `apps/eeee/tests/project_runtime/`

- [ ] Add RED coverage for browser launch, login/session, create, edit, complete, filter, delete, reload, and responsive viewport checks.
- [ ] Implement a bounded Playwright runner that starts the generated app, records action results and screenshots, and always tears down child processes.
- [ ] Store browser evidence hashes in `QA_REPORT.json`; failures must block release.
- [ ] Run the generated web project through the real browser runner.

### Task 3: Generalize project generation beyond Todo-only branching

**Files:**
- Modify: `apps/eeee/app/project_runtime/provisioner.py`, `apps/eeee/app/project_runtime/scaffold.py`, `apps/eeee/app/project_runtime/web_scaffold.py`
- Modify: `apps/eeee/app/workflow/planner.py`
- Test: `apps/eeee/tests/project_runtime/`, `apps/eeee/tests/workflow/`

- [ ] Add RED tests for dashboard, CRUD, landing page, and Todo requests producing distinct acceptance criteria and scaffold profiles.
- [ ] Move product-type selection into the request profile and keep Todo-specific checks isolated to Todo projects.
- [ ] Ensure unsupported project types return a truthful planning/block state instead of a Todo-shaped result.
- [ ] Run project-runtime regression tests.

### Task 4: Make plugin lifecycle usable without bundling connectors

**Files:**
- Modify: `apps/eeee/app/plugins/host.py`, `apps/eeee/app/assistant/router.py`, `apps/eeee/app/api/routes.py`
- Test: `apps/eeee/tests/plugins/`, `apps/eeee/tests/assistant/`

- [ ] Add RED tests for discover → permission approval → health check → invoke → disable.
- [ ] Implement natural-language plugin install/connect/disable responses with explicit permission and ClaimLatch policy metadata.
- [ ] Keep Notion, Calendar, and GitHub optional; never claim an external write when credentials are absent.
- [ ] Run plugin lifecycle tests.

### Task 5: Clean and unify verification/repository hygiene

**Files:**
- Modify: `pyproject.toml` or package test configuration, `scripts/verify-all.ps1`, `.gitignore`
- Restore/Review: `apps/eeee/tests/planning/test_models.py`, `apps/eeee/tests/planning/test_storage.py`
- Test: full Python, TypeScript, adapter, and mobile verification commands

- [ ] Add a reproducible root test command that discovers `apps/eeee/scripts` without manual environment mutation.
- [ ] Remove generated pytest/temp artifacts from the worktree and ignore future test basetemps.
- [ ] Resolve the deleted planning tests explicitly before integration.
- [ ] Run the complete verification script and record exact counts and warnings.

### Completion Gate

- [ ] Real desktop request creates at least one supported project type and returns a user-facing result.
- [ ] Specialist execution, browser E2E, QA, ClaimLatch, and release evidence are all linked by project ID and revision.
- [ ] General conversation remains natural and does not route to project execution.
- [ ] Full verification is reproducible from a clean checkout.
- [ ] No completion claim is made while any gate is blocked.
