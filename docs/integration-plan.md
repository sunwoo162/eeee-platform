# EEEE Unified Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended for this task). Steps use checkbox syntax for tracking.

**Goal:** Safely combine EEEE, ISEOL, and ClaimLatch into one local-first monorepo and implement the three critical links: ClaimLatch Adapter, EEEE persistent memory, and ISEOL independent QA results flowing into EEEE memory.

**Architecture:** Create a new eeee-platform monorepo while preserving the three existing repositories unchanged. Put EEEE under apps/eeee, ISEOL under packages/iseol, ClaimLatch under packages/claimlatch, and cross-runtime adapters/contracts under integrations. Keep Python and TypeScript dependency graphs separate and communicate through versioned local contracts.

**Tech Stack:** Python 3.12, FastAPI, SQLite, Pydantic, pytest; Node.js >=20, TypeScript, npm, Node test runner; ClaimLatch package currently reports version 0.3.86 even though its source folder is named claimlatch-v0.2.0; GitHub CLI for final publication.

**Spec:** C:/Users/user/Documents/EEEE/docs/architecture/eeee-iseol-claimlatch-organization.md

## Current implementation status (2026-10-12)

This document is the historical integration plan and its task checkboxes are retained as
traceability. The local core path described by Tasks 3–7 is now implemented in the EEEE app:

- the ClaimLatch client/process/audit boundary is in `apps/eeee/app/integrations/`;
- deterministic trust and release gates are in `apps/eeee/app/trust/` and
  `apps/eeee/app/release/`;
- persistent memory lifecycle and safe inspection controls are available through the local API;
- durable assistant jobs and the EEEE desktop/web control-center snapshot are available;
- the core acceptance command is `scripts/verify-core-product.ps1`.

The remaining unchecked items are not silently complete. They cover optional hosted providers,
the full TypeScript ISEOL Agent organization runtime, external plugin connectors, and remote
publication. Those items require their own implementation and verification before being marked
complete. The local core is considered release-ready only when the acceptance command and the
full relevant test suites pass on the current revision.

## Global Constraints

- Preserve the three existing folders; never delete, reset, or overwrite them.
- Build the unified checkout at C:/Users/user/Documents/eeee-platform.
- Do not copy .env files, credentials, node_modules, virtual environments, local databases, logs, caches, temporary workspaces, or generated build output.
- EEEE owns personal/project memory and user approval. ISEOL owns every Agent lifecycle, decomposition, routing, execution, handoff, integration, QA orchestration, and Agent evaluation.
- ClaimLatch verifies natural-language claims and release reports. Deterministic verification remains responsible for code, files, commands, tests, and runtime behavior.
- Required verification failures fail closed.
- Core operation is local-first and does not require a hosted login or central server.
- Pin the ClaimLatch source commit/version used by the adapter.

## Review Focus

- Sanitized repository import must exclude secrets, generated output, and nested Git histories; Task 1 tests the import manifest.
- Cross-runtime reports must be versioned and revision-bound; Task 2 tests schemas, correlation IDs, idempotency, and stale revisions.
- ClaimLatch failure or missing evidence must never release a trusted report or memory rule; Task 3 tests fail-closed behavior.
- One noisy lesson must not become a global Playbook rule; Task 4 tests candidate/active memory states, provenance, scope, conflicts, and promotion.
- QA must inspect the newest integrated revision and produce evidence rather than trusting Agent completion text; Task 5 tests independent QA and the memory handoff.

---

### Task 1: Create the sanitized aggregate repository

**Files:**
- Create: C:/Users/user/Documents/eeee-platform
- Create: eeee-platform/apps/eeee
- Create: eeee-platform/packages/iseol
- Create: eeee-platform/packages/claimlatch
- Create: eeee-platform/integrations
- Create: eeee-platform/docs
- Create: eeee-platform/scripts/check-repository.ps1
- Create: eeee-platform/repository-manifest.json
- Create: eeee-platform/README.md
- Create: eeee-platform/.gitignore

**Interfaces:**
- Consumes: the three existing clean checkouts and their recorded Git revisions.
- Produces: one clean root repository and a manifest containing source path, remote, branch, commit, destination, and exclusions.

- [ ] Record git rev-parse HEAD, git remote -v, git status --short, and git ls-files for all three sources.
- [ ] Copy only tracked source, tests, docs, licenses, package metadata, and the EEEE architecture document; exclude .git, .env, node_modules, .venv, dist, tmp, logs, caches, runtime data, and local databases.
- [ ] Add repository-manifest.json with schemaVersion 1 and all three source records.
- [ ] Add a repository check that detects nested Git directories, secret-like files, missing package roots, and missing source metadata.
- [ ] Run the repository check and git diff --check.
- [ ] Commit with chore: create unified EEEE platform repository.

### Task 2: Define versioned EEEE-ISEOL-QA contracts

**Files:**
- Create: integrations/contracts/project-brief.v1.schema.json
- Create: integrations/contracts/project-outcome-report.v1.schema.json
- Create: integrations/contracts/verification-envelope.v1.schema.json
- Create: integrations/contracts/memory-candidate.v1.schema.json
- Create: apps/eeee/app/integrations/contracts.py
- Create: packages/iseol/src/integrations/contracts.ts
- Test: apps/eeee/tests/integrations/test_contracts.py
- Test: packages/iseol/tests/integrations/contracts.test.ts

**Interfaces:**
- ProjectBriefV1: projectId, requestId, userGoal, scope, constraints, preferences, schedule, retrievedMemoryIds, qaBaselineIds, createdAt, schemaVersion.
- ProjectOutcomeReportV1: projectId, requestId, projectRevision, status, artifacts, agentTeams, handoffs, deterministicVerification, qaReport, claimLatchReports, receipts, risks, memoryCandidates, createdAt, schemaVersion.
- VerificationEnvelopeV1: subjectId, projectId, projectRevision, subjectType, claims, evidence, deterministicChecks, decision, claimLatchReportId, receiptId, createdAt, schemaVersion.
- MemoryCandidateV1: candidateId, kind, content, scope, sourceProjectId, sourceArtifactIds, evidenceIds, verificationIds, confidence, promotionState, createdAt, schemaVersion.

- [ ] Write failing tests for missing identifiers, unsupported versions, mismatched revisions, duplicate artifacts, invalid statuses, and reports without verification metadata.
- [ ] Implement Pydantic and TypeScript runtime validators with explicit schema-version rejection.
- [ ] Require requestId and projectRevision on every cross-boundary message.
- [ ] Make replay of an identical report idempotent and reject reports for older revisions.
- [ ] Run both contract suites and commit with feat: define versioned EEEE ISEOL contracts.

### Task 3: Implement the ClaimLatch Adapter first

**Priority:** P0

**Files:**
- Create: integrations/claimlatch-adapter/package.json
- Create: integrations/claimlatch-adapter/src/server.ts
- Create: integrations/claimlatch-adapter/src/contracts.ts
- Create: integrations/claimlatch-adapter/src/structured-output-verifier.ts
- Create: integrations/claimlatch-adapter/tests/adapter.test.ts
- Create: apps/eeee/app/integrations/claimlatch_client.py
- Create: apps/eeee/tests/integrations/test_claimlatch_client.py
- Modify: packages/iseol/src/ai-chat and release/report boundaries as needed

**Interfaces:**
- POST /v1/verify: text claim envelope to ClaimLatch VerificationEnvelopeV1.
- POST /v1/verify-structured: structured action plus application policy to deterministic PASS/BLOCK.
- ClaimLatchClient.verify_text(input) -> VerificationEnvelopeV1.
- ClaimLatchClient.verify_structured(input) -> VerificationEnvelopeV1.
- ClaimLatchClient.require_pass(input) -> VerifiedResult or VerificationBlocked.

- [ ] Write failing tests for PASS, BLOCK, unsupported claims, missing evidence, malformed reports, provider errors, structured actions outside allowlists, and receipt linkage.
- [ ] Pin the actual ClaimLatch package version and source commit. Do not infer version from the folder name.
- [ ] Use ClaimLatch verifyBeforeRelease for textual results and expose only a controlled loopback/process boundary to Python.
- [ ] Add the structured-output policy layer for workspace paths, tool allowlists, external transfer, delete, publish, deploy, and message-send actions.
- [ ] Persist ClaimLatch report ID, receipt ID, payload hash, policy version, adapter version, ClaimLatch version, and project revision.
- [ ] Make transport errors, verifier errors, and missing evidence fail closed.
- [ ] Add release hooks for Agent handoffs, QA summaries, final reports, and memory candidates.
- [ ] Run adapter tests and commit with feat: add local ClaimLatch release adapter.

### Task 4: Implement EEEE persistent memory and promotion

**Priority:** P0

**Files:**
- Create: apps/eeee/app/memory/models.py
- Create: apps/eeee/app/memory/store.py
- Create: apps/eeee/app/memory/compiler.py
- Create: apps/eeee/app/memory/retriever.py
- Create: apps/eeee/app/memory/promotion.py
- Modify: apps/eeee/app/storage/sqlite.py with versioned memory tables and migrations
- Test: apps/eeee/tests/memory/test_memory_store.py
- Test: apps/eeee/tests/memory/test_memory_compiler.py
- Test: apps/eeee/tests/memory/test_memory_promotion.py
- Test: apps/eeee/tests/memory/test_memory_retrieval.py

**Interfaces:**
- MemoryStore.save_candidate(candidate: MemoryCandidateV1) -> MemoryRecord.
- MemoryStore.promote(candidate_id, actor, evidence) -> MemoryRecord.
- MemoryStore.supersede(memory_id, replacement_id) -> MemoryRecord.
- MemoryStore.revoke(memory_id, reason) -> MemoryRecord.
- MemoryRetriever.search(query, scope, filters) -> list[MemoryRecord].
- MemoryCompiler.compile(outcome_report) -> list[MemoryCandidateV1].

- [ ] Write failing tests for candidate/active/superseded/revoked states, provenance, project scope, duplicate reports, conflicts, expiry, and user deletion.
- [ ] Add SQLite migrations for memory records separate from raw events.
- [ ] Require source project, source artifacts, verification IDs, scope, confidence meaning, timestamps, and optional expiry.
- [ ] Compile successful patterns, failed patterns, QA rules, regression rules, Agent routing hints, and Playbook proposals from ProjectOutcomeReportV1.
- [ ] Keep compilation separate from promotion; no candidate becomes active automatically without policy.
- [ ] Require ClaimLatch evidence for external factual rules and deterministic evidence for code/QA rules.
- [ ] Require explicit user approval or repeated validated evidence for organization-wide Playbook rules.
- [ ] Implement scoped retrieval by project type, technology, feature, risk, recency, verification status, and user approval.
- [ ] Run memory tests and commit with feat: add persistent project memory and promotion pipeline.

### Task 5: Implement independent QA and connect QA results to EEEE memory

**Priority:** P0

**Files:**
- Create: packages/iseol/src/qa/qa-plan.ts
- Create: packages/iseol/src/qa/qa-orchestrator.ts
- Create: packages/iseol/src/qa/evidence-ledger.ts
- Create: packages/iseol/src/qa/release-gate.ts
- Create: packages/iseol/tests/qa/qa-orchestrator.test.ts
- Create: packages/iseol/tests/qa/release-gate.test.ts
- Create: apps/eeee/app/domain/qa_models.py
- Modify: apps/eeee/app/coordinator/service.py
- Test: apps/eeee/tests/coordinator/test_qa_memory_flow.py

**Interfaces:**
- QaPlan.build(projectBrief, retrievedQualityMemory) -> QaPlan.
- QaOrchestrator.run(plan, workspace, revision) -> QaReportV1.
- EvidenceLedger.record(evidence) -> EvidenceId.
- ReleaseGate.evaluate(qaReport, deterministicReport, verificationEnvelope) -> PASS | WARN | BLOCKED.
- MemoryCompiler.compile(verifiedOutcomeReport) -> MemoryCandidateV1 list.

- [ ] Write failing tests for QA-0 through QA-5, required evidence, latest-revision checks, stale report rejection, and Agent completion text being insufficient.
- [ ] Represent acceptance criteria, risk, required checks, inherited regression rules, and release thresholds as structured QA data.
- [ ] Reuse the existing deterministic EEEE harness verifier and ISEOL evidence instead of creating a second unrestricted command runner.
- [ ] Record command, exit status, stdout/stderr hash, workspace, revision, artifact paths, and verification IDs for every check.
- [ ] Return findings with severity, reproduction steps, evidence IDs, owner Workstream, and required action.
- [ ] Route blocking findings back to ISEOL without changing them into memory.
- [ ] After QA passes, create ProjectOutcomeReportV1 and send it through ClaimLatch before memory compilation.
- [ ] Compile QA failures and successes into candidates, but only promote them through Task 4 policy.
- [ ] Add a test proving Project A’s validated responsive defect becomes Project B’s QA baseline without importing raw unverified text.
- [ ] Run Python and TypeScript QA tests and commit with feat: connect independent QA to persistent memory.

### Task 6: Connect EEEE memory to ISEOL dynamic Agent planning

**Files:**
- Create: packages/iseol/src/agent-organization/registry.ts
- Create: packages/iseol/src/agent-organization/task-decomposer.ts
- Create: packages/iseol/src/agent-organization/team-composer.ts
- Create: packages/iseol/src/agent-organization/qa-baseline.ts
- Test: packages/iseol/tests/agent-organization/team-composer.test.ts
- Test: packages/iseol/tests/agent-organization/qa-baseline.test.ts
- Modify: apps/eeee/app/coordinator/service.py
- Test: apps/eeee/tests/coordinator/test_memory_project_flow.py

- [ ] Test a previous responsive defect creating a required viewport check, a successful API/DB sequencing pattern creating a dependency, and a small project collapsing unnecessary parallel teams.
- [ ] Model Role, Workstream, Team, Agent Instance, Task, capability, permissions, and performance separately.
- [ ] Retrieve scoped EEEE memory before dispatch and preserve memory IDs in the generated ProjectBrief and QaPlan.
- [ ] Keep ISEOL as the sole owner of Agent creation, routing, handoff, retry, integration, and evaluation.
- [ ] Run cross-runtime tests and commit with feat: make ISEOL planning memory-aware.

### Task 7: Add local runtime, security checks, and end-to-end proof

**Files:**
- Create: scripts/dev-up.ps1
- Create: scripts/verify-all.ps1
- Create: docs/operations/local-runtime.md
- Create: docs/security/trusted-release-boundary.md
- Create: tests/e2e/test_project_memory_qa_loop.ps1
- Copy/update: docs/architecture/eeee-iseol-claimlatch-organization.md

- [ ] Start EEEE, ISEOL, and ClaimLatch only on loopback with health checks.
- [ ] Verify workspace path boundaries, command allowlists, no-secret import, external network policy, structured action allowlists, receipt permissions, and approval requirements.
- [ ] Run one local fixture through request, memory retrieval, ISEOL plan, Agent evidence, independent QA, ClaimLatch final report, memory candidate, and next-project QA baseline.
- [ ] Run scripts/verify-all.ps1 and require Python tests, TypeScript tests, adapter tests, contract tests, repository hygiene, and the end-to-end loop to pass.
- [ ] Commit with test: verify local EEEE ISEOL ClaimLatch workflow.

### Task 8: Publish the aggregate GitHub repository

**Default target:** sunwoo162/eeee-platform, public. Keep this configurable until the final creation command.

**Files:**
- Modify: eeee-platform/README.md with setup, component map, verification commands, and upstream attribution.
- Create: eeee-platform/.github/workflows/verify.yml

- [ ] Run the full verification and secret scan before any remote creation.
- [ ] Create the repository with gh repo create only after the local initial commit passes.
- [ ] Push main and attach the created repository artifact.
- [ ] Record all three upstream remotes and imported commits in repository-manifest.json.
- [ ] Leave the original repositories preserved as reference/upstream checkouts unless the user later chooses a migration policy.

## Self-Review Results

- Spec coverage: repository consolidation, EEEE/ISEOL ownership, dynamic Agent organization, independent QA, ClaimLatch integration, persistent memory, memory-informed next-project QA, local runtime, and GitHub aggregation are covered.
- Priority coverage: ClaimLatch Adapter, EEEE memory lifecycle, and ISEOL QA-to-memory flow are explicit P0 tasks.
- Fail-closed coverage: ClaimLatch failure, stale revisions, missing evidence, structured action violations, and untrusted memory promotion have dedicated tests.
- Known deferred scope: full calendar, communications, and life-management automation remain after the first vertical project-memory/QA loop.
- No destructive migration: existing folders remain unchanged and the new aggregate repository becomes authoritative only after verification.

## Execution Handoff

The plan is complete and saved to docs/superpowers/plans/2026-10-06-eeeee-unified-platform.md. Review it before implementation begins. Native execution with one final independent review is recommended because the P0 tasks share cross-language contracts and persistence boundaries.
