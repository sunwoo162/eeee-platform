# Gleave Project Portfolio Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user generate six evidence-backed portfolio artifacts from a
Gleave project by pressing one button or asking EEEE to organize the project
for a portfolio.

**Architecture:** Add a focused `app.portfolio` package that reads existing
project, task, run, harness, ClaimLatch, QA, memory, and workspace records into
an immutable revision snapshot. A deterministic fact/provenance layer will
feed format-specific Markdown renderers, with an optional narrative-editor
port kept behind an interface. Wire the generator into EEEE routing, local
FastAPI endpoints, and the existing Gleave project view without changing the
project execution engine.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, existing Git CLI,
vanilla JavaScript/CSS, pytest, and Node's built-in test runner. No new runtime
dependency.

**Spec:** `docs/superpowers/specs/2026-10-06-project-portfolio-generation-design.md`

## Global Constraints

- Every factual section in a generated artifact must be traceable to durable project evidence.
- Generation is local-first, does not publish externally, and redacts secrets and private values by default.
- Missing evidence is shown as missing instead of being guessed.
- A project revision creates an immutable source snapshot; regeneration must not mutate an older snapshot.
- Korean is the default output language and English is selectable.
- The six output kinds are `portfolio-page`, `github-readme`, `retrospective`, `technical-blog`, `resume-summary`, and `interview-guide`.
- Existing request/run, memory, ClaimLatch, desktop, and mobile APIs must remain backward compatible.
- External publishing is not part of this increment; only local project files are written.

## Review Focus

- A project with no Git repository still generates truthful documents with a visible Git evidence warning; test in Task 2.
- A project with secrets in task events, diffs, or artifacts never emits those secrets; test in Task 3.
- A stale project revision cannot overwrite a newer portfolio snapshot; test in Task 1 and Task 4.
- Missing ClaimLatch or QA evidence is reported as coverage gaps rather than PASS or invented metrics; test in Task 3.
- Repeating generation for the same project, revision, language, and formats is idempotent and does not duplicate artifacts; test in Task 4 and Task 6.

---

### Task 1: Durable troubleshooting, snapshot, and artifact records

**Files:**
- Create: `apps/eeee/app/portfolio/__init__.py`
- Create: `apps/eeee/app/portfolio/models.py`
- Modify: `apps/eeee/app/storage/sqlite.py`
- Test: `apps/eeee/tests/portfolio/__init__.py`
- Test: `apps/eeee/tests/portfolio/test_storage.py`

**Interfaces:**
- Produces `TroubleshootingRecord`, `PortfolioSourceSnapshot`,
  `PortfolioArtifactRecord`, `PortfolioFormat`, and `PortfolioLanguage`.
- Produces `SQLiteStore.create_troubleshooting_record(record)`,
  `list_troubleshooting_records(project_id, project_revision)`,
  `update_troubleshooting_record(record)`, `save_portfolio_snapshot(snapshot)`,
  `get_portfolio_snapshot(snapshot_id)`, `save_portfolio_artifact(record)`,
  and `list_portfolio_artifacts(project_id, source_snapshot_id=None)`.
- All persistence methods reject an empty project identity and preserve the
  project revision in every row.

- [ ] **Step 1: Write failing model and SQLite tests**

  Add tests for creating/updating a troubleshooting record, filtering records
  by project revision, saving an immutable source snapshot, storing an output
  artifact with its content hash, and refusing to replace a snapshot with a
  different revision under the same snapshot ID.

- [ ] **Step 2: Run the focused tests to verify they fail**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/portfolio/test_storage.py`

  Expected: FAIL because the `app.portfolio` models and store methods do not
  exist.

- [ ] **Step 3: Implement strict portfolio models**

  Use frozen Pydantic models with aliases matching the existing JSON API style.
  Keep troubleshooting observations and attempts as ordered structured values,
  not untyped prose blobs, and include source references on snapshots and
  generated artifacts.

- [ ] **Step 4: Add SQLite tables and store methods**

  Add migration-safe `CREATE TABLE IF NOT EXISTS` definitions for
  `troubleshooting_records`, `portfolio_snapshots`, and `portfolio_artifacts`.
  Serialize structured payloads as JSON while keeping project, revision, kind,
  language, status, and content hash queryable. Enforce revision checks in the
  store so old snapshots cannot overwrite newer evidence.

- [ ] **Step 5: Run storage tests**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/portfolio/test_storage.py`

  Expected: all focused persistence tests pass.

- [ ] **Step 6: Commit**

  `git add apps/eeee/app/portfolio apps/eeee/app/storage/sqlite.py apps/eeee/tests/portfolio && git commit -m "feat: persist portfolio evidence records"`

### Task 2: Evidence collection and Git history adapter

**Files:**
- Create: `apps/eeee/app/portfolio/sources.py`
- Create: `apps/eeee/app/portfolio/git.py`
- Test: `apps/eeee/tests/portfolio/test_sources.py`
- Test: `apps/eeee/tests/portfolio/test_git.py`

**Interfaces:**
- Produces `PortfolioSourceCollector.collect(project_id, project_revision) -> PortfolioSourceSnapshot`.
- Produces `GitHistoryReader.read(workspace: Path) -> GitEvidence` with branch,
  commits, changed files, and repository availability.
- The collector consumes `SQLiteStore`, `Coordinator`, ClaimLatch audit data,
  and `GitHistoryReader`; it does not call external connectors.

- [ ] **Step 1: Write failing Git reader tests**

  Use a fake command runner to pin parsing of branch name, ordered commit
  records, changed files, and diff summaries. Add a repository-missing case
  that returns `available=False` and a warning instead of raising.

- [ ] **Step 2: Run Git tests to verify they fail**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/portfolio/test_git.py`

  Expected: FAIL because the Git evidence reader is not implemented.

- [ ] **Step 3: Implement `GitHistoryReader`**

  Execute only read-only Git commands in the project workspace, normalize
  commit timestamps and hashes, cap history/diff sizes using existing settings,
  and return explicit warnings for a missing or unreadable repository.

- [ ] **Step 4: Write failing source collector tests**

  Seed project profile, tasks, runs, reports, harness state, ClaimLatch audit,
  QA artifacts, troubleshooting records, and promoted memory. Assert that one
  snapshot contains each source category, preserves source IDs, and is scoped to
  the requested project revision.

- [ ] **Step 5: Implement `PortfolioSourceCollector`**

  Read all local stores and the Git reader into one immutable snapshot. Include
  coverage warnings when Git, QA, or ClaimLatch evidence is absent. Never
  invoke Notion, GitHub, Calendar, mobile, or other external connectors.

- [ ] **Step 6: Run source tests**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/portfolio/test_git.py apps/eeee/tests/portfolio/test_sources.py`

  Expected: all evidence collection tests pass.

- [ ] **Step 7: Commit**

  `git add apps/eeee/app/portfolio/git.py apps/eeee/app/portfolio/sources.py apps/eeee/tests/portfolio/test_git.py apps/eeee/tests/portfolio/test_sources.py && git commit -m "feat: collect portfolio project evidence"`

### Task 3: Fact sheet, redaction, provenance, and Markdown renderers

**Files:**
- Create: `apps/eeee/app/portfolio/redaction.py`
- Create: `apps/eeee/app/portfolio/facts.py`
- Create: `apps/eeee/app/portfolio/renderers.py`
- Test: `apps/eeee/tests/portfolio/test_redaction.py`
- Test: `apps/eeee/tests/portfolio/test_renderers.py`

**Interfaces:**
- Produces `RedactionResult` and `redact_private_values(text) -> RedactionResult`.
- Produces `PortfolioFactSheet` and `build_fact_sheet(snapshot) -> PortfolioFactSheet`.
- Produces `PortfolioRenderer.render(facts, kind, language) -> RenderedArtifact`.
- Each `RenderedArtifact` contains Markdown, content hash, coverage warnings,
  and section-to-source references for `portfolio-manifest.json`.

- [ ] **Step 1: Write failing redaction tests**

  Pin removal of API keys, GitHub tokens, private-key blocks, bearer tokens,
  configured connector values, and path values marked private. Assert ordinary
  commit hashes, filenames, and Korean/English prose remain unchanged.

- [ ] **Step 2: Run redaction tests to verify they fail**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/portfolio/test_redaction.py`

  Expected: FAIL because the redaction module is not implemented.

- [ ] **Step 3: Implement redaction and fact extraction**

  Build a normalized fact sheet from the snapshot, preserving source IDs and
  marking unsupported claims as missing. Keep facts separate from prose so a
  renderer cannot silently invent a metric, technology, or outcome.

- [ ] **Step 4: Write failing renderer tests**

  For one seeded fact sheet, assert that all six kinds render required factual
  sections in Korean, English rendering changes labels but not source facts,
  missing QA/ClaimLatch/Git evidence becomes a warning, and the manifest maps
  each rendered section to source IDs.

- [ ] **Step 5: Implement deterministic Markdown renderers**

  Add format-specific templates for the six output kinds. Use the same fact
  sheet and provenance map for every format. Keep optional narrative editing
  behind a protocol; the first implementation must work without an LLM.

- [ ] **Step 6: Run renderer tests**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/portfolio/test_redaction.py apps/eeee/tests/portfolio/test_renderers.py`

  Expected: all redaction, format, language, coverage, and provenance tests
  pass.

- [ ] **Step 7: Commit**

  `git add apps/eeee/app/portfolio/redaction.py apps/eeee/app/portfolio/facts.py apps/eeee/app/portfolio/renderers.py apps/eeee/tests/portfolio/test_redaction.py apps/eeee/tests/portfolio/test_renderers.py && git commit -m "feat: render evidence-backed portfolio artifacts"`

### Task 4: Portfolio service, assistant capability, and API

**Files:**
- Create: `apps/eeee/app/portfolio/service.py`
- Modify: `apps/eeee/app/assistant/registry.py`
- Modify: `apps/eeee/app/assistant/service.py`
- Modify: `apps/eeee/app/api/routes.py`
- Modify: `apps/eeee/app/main.py`
- Test: `apps/eeee/tests/portfolio/test_service.py`
- Test: `apps/eeee/tests/api/test_portfolio_routes.py`
- Test: `apps/eeee/tests/assistant/test_assistant_service.py`

**Interfaces:**
- Produces `PortfolioService.generate(project_id, formats, language, revision=None) -> PortfolioGenerationResult`.
- Produces `PortfolioService.list_artifacts(project_id) -> list[PortfolioArtifactRecord]`.
- Adds assistant capability ID `portfolio-generation` with local side effects
  and user approval required before overwriting existing outputs.
- Adds `POST /api/projects/{project_id}/portfolio`,
  `GET /api/projects/{project_id}/portfolio`, and
  `GET /api/projects/{project_id}/portfolio/{artifact_id}`.

- [ ] **Step 1: Write failing service and routing tests**

  Pin generation of all six default formats, selected-format regeneration,
  Korean default, English selection, same-revision idempotency, stale-revision
  rejection, existing-artifact overwrite protection, and missing-evidence
  warnings. Pin assistant text routing for the Korean phrase
  `이 프로젝트 포트폴리오로 정리해줘`.

- [ ] **Step 2: Run focused tests to verify they fail**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/portfolio/test_service.py apps/eeee/tests/api/test_portfolio_routes.py apps/eeee/tests/assistant/test_assistant_service.py`

  Expected: FAIL because the service, capability, and routes are not wired.

- [ ] **Step 3: Implement `PortfolioService`**

  Coordinate snapshot collection, fact extraction, rendering, manifest
  persistence, and output writes under `<workspace>/docs/portfolio/`. Use a
  stable request key for idempotency and write a new artifact revision instead
  of replacing an artifact from another source snapshot.

- [ ] **Step 4: Add assistant capability and application wiring**

  Register `portfolio-generation`, add an assistant-service method that
  resolves a project ID from explicit context or the selected project, and
  publish start/completion/failure events through the existing local event
  publisher. Keep project execution routing unchanged.

- [ ] **Step 5: Add API endpoints and response models**

  Validate project identity, language, format names, and revision. Return
  artifact metadata, coverage warnings, and local paths while never returning
  secrets or raw prompts. Map stale revisions to a conflict response and
  generation failures to a truthful error response with the snapshot retained.

- [ ] **Step 6: Run service and API tests**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/portfolio/test_service.py apps/eeee/tests/api/test_portfolio_routes.py apps/eeee/tests/assistant/test_assistant_service.py`

  Expected: all service, routing, idempotency, revision, and API tests pass.

- [ ] **Step 7: Commit**

  `git add apps/eeee/app/portfolio/service.py apps/eeee/app/assistant/registry.py apps/eeee/app/assistant/service.py apps/eeee/app/api/routes.py apps/eeee/app/main.py apps/eeee/tests/portfolio/test_service.py apps/eeee/tests/api/test_portfolio_routes.py apps/eeee/tests/assistant/test_assistant_service.py && git commit -m "feat: expose portfolio generation through EEEE"`

### Task 5: Gleave project-view controls and artifact preview

**Files:**
- Modify: `apps/eeee/app/static/index.html`
- Modify: `apps/eeee/app/static/app.js`
- Modify: `apps/eeee/app/static/styles.css`
- Test: `apps/eeee/tests/ui_portfolio_generation.js`
- Test: `apps/eeee/tests/api/test_request_flow.py` (existing HTML contract assertions)

**Interfaces:**
- Consumes the Task 4 endpoints and the selected project/request state.
- Produces a `포트폴리오로 정리` action, language selector, format selection,
  generation status, coverage warnings, artifact preview/open links, and
  manifest/source-snapshot links.

- [ ] **Step 1: Write failing UI contract tests**

  Assert the page contains the portfolio action, six format identifiers,
  Korean-first labels, English selection, warning/result containers, and no
  external publish action.

- [ ] **Step 2: Run UI tests to verify they fail**

  Run: `node --test apps/eeee/tests/ui_portfolio_generation.js`

  Expected: FAIL because the controls and rendering handlers are absent.

- [ ] **Step 3: Add the portfolio panel to `index.html`**

  Place the action near the project/run summary. Add six format cards, language
  control, progress/status region, coverage warnings, preview area, output
  paths, and provenance links. Keep the existing run and research controls
  backward compatible until the one-click project flow replaces them in its
  own change.

- [ ] **Step 4: Implement `app.js` state and API handlers**

  Add portfolio state keyed by project/revision, call the Task 4 endpoints,
  render generated artifacts and warnings, prevent duplicate submissions, and
  preserve Korean default with English selection. Handle stale responses using
  the existing request-selection race pattern.

- [ ] **Step 5: Add focused styles**

  Match the current calm Gleave visual system, keep the panel readable at
  desktop companion/browser widths, and make failure, missing evidence, and
  generated states visually distinct without flashing or continuous animation.

- [ ] **Step 6: Run UI verification**

  Run: `node --test apps/eeee/tests/ui_portfolio_generation.js`

  Expected: all UI contract and interaction tests pass.

- [ ] **Step 7: Commit**

  `git add apps/eeee/app/static apps/eeee/tests/ui_portfolio_generation.js apps/eeee/tests/api/test_request_flow.py && git commit -m "feat: add Gleave portfolio generation view"`

### Task 6: End-to-end acceptance, documentation, and regression verification

**Files:**
- Create: `apps/eeee/tests/e2e/test_portfolio_generation.py`
- Modify: `README.md`
- Modify: `docs/operations/local-runtime.md` (if the existing operations guide documents project artifacts)

**Interfaces:**
- Consumes the complete Task 4 service/API and Task 5 UI surface.
- Produces a seeded-project acceptance test and local usage documentation.

- [ ] **Step 1: Write the end-to-end acceptance test**

  Seed one project with commits, a troubleshooting record, a passing and a
  missing QA/ClaimLatch evidence case, generate all six formats, and assert
  the six files, manifest references, redactions, warnings, and stable hashes
  on repeated generation.

- [ ] **Step 2: Run the acceptance test to verify the integrated flow**

  Run: `C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests/e2e/test_portfolio_generation.py`

  Expected: PASS after Tasks 1–5 are complete.

- [ ] **Step 3: Document the user flow**

  Add the exact Korean command, button flow, default output directory,
  six-file list, evidence warnings, and local-only publishing rule to the
  existing local runtime documentation and README without claiming automatic
  public publishing.

- [ ] **Step 4: Run the full relevant verification suite**

  Run:

  ```powershell
  C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe -m pytest -q apps/eeee/tests
  node --check apps/eeee/app/static/app.js
  node --test apps/eeee/tests/ui_portfolio_generation.js
  .\scripts\verify-all.ps1 -Full
  ```

  Expected: all existing and new tests pass, JavaScript syntax validation
  passes, and the repository verification script reports success.

- [ ] **Step 5: Commit**

  `git add apps/eeee/tests/e2e/test_portfolio_generation.py README.md docs/operations/local-runtime.md && git commit -m "test: verify evidence-backed portfolio generation"`

