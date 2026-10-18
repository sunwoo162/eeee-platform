# ISEOL Natural-Language Project Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 “오늘 식단 정리해주는 웹 만들어줘”처럼 한 문장만 입력해도 EEEE가 필요한 작업만 자동 구성하고, 로컬 웹 결과물을 구현·검증·보고하는 ISEOL 실행 경로를 만든다.

**Architecture:** 기존 EEEE FastAPI·SQLite·백그라운드 작업·ClaimLatch·웹 실행기를 유지한다. 자연어 입력은 정규화된 프로젝트 의도와 기본 가정으로 변환되고, ISEOL은 의도에 맞는 단계·작업·검증 그래프만 컴파일한다. 플러그인 자체는 이번 범위에서 구현하지 않으며, 나중에 도메인 플러그인·커넥터·프로비저너·검증기를 등록할 수 있는 읽기 전용 확장 계약만 제공한다.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, pytest, 기존 EEEE `AgentRuntime`·`ExecutionStore`·`ClaimLatch`·`WebProjectRunner`.

**Spec:** `docs/superpowers/specs/2026-10-16-iseol-project-execution-design.md`

## Global Constraints

- 사용자 입력은 자연어 한 문장으로 시작하며 사용자가 봇·단계·기술 스택을 직접 선택하지 않아도 된다.
- 부족한 정보만으로 작업 전체를 중단하지 말고 기본 가정을 기록한 뒤 진행한다.
- 핵심 결과가 달라지거나 인증·결제·개인정보·외부 리소스·실제 배포가 필요한 경우에만 질문을 묶어서 한 번 요청한다.
- 외부 계정 연결·저장소/문서/Discord 생성·메일 발송·운영 배포는 플러그인이 구현되기 전까지 실행하지 않고 `awaiting_configuration` 또는 `awaiting_approval`로 기록한다.
- 플러그인 구현, OAuth 제공자별 API 구현, Discord/GitHub/Notion 리소스 생성은 이번 계획의 범위가 아니다.
- ISEOL은 현재 연결된 `AgentRuntime`이 실제로 실행한 증거가 없으면 완료로 보고하지 않는다.
- 프로젝트와 실행은 `WORKSPACE_ROOT` 아래로 제한하며 재시도·재시작은 동일 project/request/workspace를 재사용한다.
- 생성·수정되는 텍스트 파일은 UTF-8, `ensure_ascii=False`, LF 개행을 사용하고 replacement character·BOM·`git diff --check`를 검증한다.
- 기존 테스트와 기존 API 응답 호환성을 유지하며, 새 필드는 선택적으로 추가한다.
- 새 런타임 의존성은 추가하지 않는다.
- 템플릿에 정확히 매칭되지 않는 웹 요청은 범용 웹 템플릿과 연결된 `AgentRuntime`으로 처리하되, 템플릿 특화 검증을 통과했다고 거짓 보고하지 않는다.
- 자연어 해석의 원천은 하나만 유지한다. 기존 `RequestBrief`는 새 `ProjectIntent`에서 생성하는 호환 모델로 사용한다.

## Review Focus

- **한국어·긴 자연어 요청:** 문장 정규화 때문에 핵심 목적이나 원문이 사라지지 않아야 한다. `test_intake_preserves_original_and_extracts_korean_meal_web_request`가 고정한다.
- **모호한 요청:** “이거 해줘”는 임의의 프로젝트를 만들지 않고 묶인 최소 질문으로 멈춰야 한다. `test_intake_bundles_only_blocking_questions`가 고정한다.
- **플러그인 미설치 상태:** 필요한 확장이 없어도 로컬 결과는 가능한 만큼 만들고 외부 액션을 실행하지 않아야 한다. `test_extension_registry_reports_missing_without_side_effect`가 고정한다.
- **재시작·재시도:** 동일 요청을 재실행해도 두 프로젝트·두 작업공간·중복 산출물이 생기지 않아야 한다. `test_orchestrator_resume_is_idempotent`가 고정한다.
- **부분 실패와 품질 주장:** 에이전트나 검증기가 실패하면 최종 상태가 `completed`가 아니며 실패·증거·남은 작업이 보고되어야 한다. `test_final_report_blocks_false_completion`이 고정한다.

---

### Task 1: Canonical intake and project contracts

**Files:**
- Create: `apps/eeee/app/iseol/contracts.py`
- Create: `apps/eeee/app/iseol/intake.py`
- Modify: `apps/eeee/app/project_runtime/models.py: ProjectProfile`
- Modify: `apps/eeee/app/iseol/__init__.py`
- Test: `apps/eeee/tests/iseol/test_intake.py`
- Test: `apps/eeee/tests/project_runtime/test_project_runtime_models.py`

**Interfaces:**
- Produces `ProjectIntent`, `ClarificationQuestion`, `IntakeResult`, `ExternalAction`, and `ProjectExecutionPlan` Pydantic models with camel-case aliases and `extra="forbid"`.
- Produces `NaturalLanguageIntake.parse(text: str) -> IntakeResult`.
- `ProjectIntent` must retain `raw_text`, normalized `goal`, `project_type`, `template_id`, `constraints`, `assumptions`, `acceptance_criteria`, `risk_level`, and `requires_external_approval`.
- `ProjectProfile` gains optional `template_id`, `assumptions`, and `quality_report_path` fields without invalidating existing stored profiles.

- [ ] **Step 1: Write the failing intake and model tests**

  Add `test_intake_preserves_original_and_extracts_korean_meal_web_request` asserting that `오늘 식단 정리해주는 웹 만들어줘` produces `project_type == "web_app"`, `template_id == "meal_planner"`, local-first assumptions, non-empty acceptance criteria, and the exact original text.

  Add `test_intake_bundles_only_blocking_questions` asserting that a vague request returns one or more blocking questions without inventing a project type, while a concrete local web request returns no blocking question.

  Add model round-trip coverage for camel-case JSON and loading a legacy `ProjectProfile` without the new optional fields.

- [ ] **Step 2: Run the focused tests and verify they fail for the missing contracts**

  Run: `python -m pytest tests/iseol/test_intake.py tests/project_runtime/test_project_runtime_models.py -q` from `apps/eeee`.

  Expected: FAIL because the new contracts and parser are not defined.

- [ ] **Step 3: Implement the contracts and deterministic intake parser**

  Implement `NaturalLanguageIntake.parse` as a bounded classifier, not an LLM call. Preserve the original text, detect web/meal/todo/site intents, record assumptions explicitly, and produce at most one bundled clarification set for core ambiguity. Do not create projects or call connectors from this module.

- [ ] **Step 4: Run the focused tests and verify they pass**

  Run the same pytest command.

  Expected: PASS, including legacy profile validation.

### Task 2: Lazy extension and plugin boundary

**Files:**
- Create: `apps/eeee/app/iseol/extensions.py`
- Modify: `apps/eeee/app/plugins/models.py: plugin manifest compatibility fields only if required`
- Modify: `apps/eeee/app/plugins/registry.py: adapter entry point only if required`
- Modify: `apps/eeee/app/iseol/__init__.py`
- Test: `apps/eeee/tests/iseol/test_extensions.py`

**Interfaces:**
- Produces `ExtensionKind = Literal["domain", "connector", "provisioner", "worker", "validator"]`.
- Produces immutable `ExtensionManifest(id, version, kind, capabilities, required_connectors, side_effect_level, enabled)`.
- Produces `ExtensionRegistry.register(manifest)`, `ExtensionRegistry.select(capability_ids) -> list[ExtensionManifest]`, and `ExtensionRegistry.missing(required_ids) -> list[str]`.
- The registry is metadata-only in this task. It does not install, authenticate, import arbitrary code, open a browser, or mutate external services.

- [ ] **Step 1: Write the failing registry tests**

  Add `test_extension_registry_reports_missing_without_side_effect`, `test_extension_selection_is_capability_scoped`, and `test_disabled_extension_is_not_selected`.

  Assert that selecting a local meal web project never loads unrelated connectors and that missing external extensions are returned as data.

- [ ] **Step 2: Run the focused tests and verify they fail**

  Run: `python -m pytest tests/iseol/test_extensions.py -q`.

  Expected: FAIL because the extension boundary does not exist.

- [ ] **Step 3: Implement the lazy registry**

  Keep manifests serializable and versioned. Use capability IDs rather than provider names so future Figma/Gmail/GitHub/Notion/Discord implementations can register later without changing ISEOL orchestration. Make repeated registration of the same `(id, version)` idempotent and reject conflicting definitions.

- [ ] **Step 4: Run the focused tests and verify they pass**

  Run: `python -m pytest tests/iseol/test_extensions.py -q`.

  Expected: PASS with no external process or network activity.

### Task 3: Dynamic phase and agent-graph compiler

**Files:**
- Create: `apps/eeee/app/iseol/graph.py`
- Modify: `apps/eeee/app/iseol/agents.py: AgentNode and AgentTeamFactory`
- Modify: `apps/eeee/app/project_runtime/iseol_bridge.py: graph compilation handoff`
- Test: `apps/eeee/tests/iseol/test_graph_compiler.py`
- Modify: `apps/eeee/tests/iseol/test_agent_team.py`

**Interfaces:**
- Produces `AgentGraphCompiler.compile(intent: ProjectIntent, extensions: ExtensionRegistry) -> AgentGraph`.
- Adds `phase`, `validators`, `extension_ids`, and `side_effect_level` to `AgentNode` with safe defaults for existing graphs.
- Keeps `AgentTeamFactory.default_graph` as a compatibility fixture, but new project runs use `AgentGraphCompiler`.
- A compiled graph must have unique task IDs, no cycles, explicit dependencies, and a final `review`/`integration` gate.

- [ ] **Step 1: Write failing compiler tests**

  Add tests that compile a meal web intent into only relevant phases: intake, definition, requirements, content, IA/UX, UI, technical design, environment, implementation, testing, release, and documentation/operations handoff.

  Assert that unrelated connector workers are absent, frontend/QA dependencies are ordered, every implementation task has a validator, and a deliberately cyclic catalog is rejected.

- [ ] **Step 2: Run the compiler tests and verify failure**

  Run: `python -m pytest tests/iseol/test_graph_compiler.py tests/iseol/test_agent_team.py -q`.

  Expected: FAIL because graph compilation and node metadata are missing.

- [ ] **Step 3: Implement the phase catalog and compiler**

  Define built-in core roles for planning, research, requirements, content, design, architecture, frontend, test, accessibility, security, review, documentation, and integration. Use the intent/template and extension registry to omit unnecessary roles. Validate dependencies with a topological sort before returning the graph.

- [ ] **Step 4: Update the plan bridge to persist the compiled graph**

  Keep the existing versioned JSON stdin/stdout boundary for compatibility, but make the Python `AgentGraphCompiler` the source of truth. The Node `plan-cli.js` bridge becomes optional compatibility input and must not block a native run when it is unavailable. Include `intent`, `assumptions`, `selectedExtensions`, and `missingExtensions` in `execution-plan.json`.

- [ ] **Step 5: Run focused tests and verify pass**

  Run: `python -m pytest tests/iseol/test_graph_compiler.py tests/iseol/test_agent_team.py tests/project_runtime/test_iseol_bridge.py -q`.

  Expected: PASS and the legacy graph compatibility tests remain green.

### Task 4: ISEOL orchestrator and idempotent local execution

**Files:**
- Create: `apps/eeee/app/iseol/orchestrator.py`
- Modify: `apps/eeee/app/kernel/capabilities.py: ProjectExecutionCapability`
- Modify: `apps/eeee/app/project_runtime/provisioner.py`
- Modify: `apps/eeee/app/assistant/service.py` only for preserved result fields if needed
- Test: `apps/eeee/tests/iseol/test_orchestrator.py`
- Modify: `apps/eeee/tests/e2e/test_core_project_flow.py`
- Modify: `apps/eeee/tests/e2e/test_assistant_project_runtime.py`

**Interfaces:**
- Produces `IseolOrchestrator.run(request: AssistantRequest, context: AssistantContext, envelope: ExecutionEnvelope) -> CapabilityOutcome`.
- Produces `IseolOrchestrator.resume(project_id: str, request: AssistantRequest, context: AssistantContext, envelope: ExecutionEnvelope) -> CapabilityOutcome`.
- `ProjectExecutionCapability` becomes a thin adapter that builds the plan and delegates the actual run to `IseolOrchestrator`.
- The outcome keeps existing keys (`projectId`, `projectProfile`, `executionPlanPath`, `agentExecutionReport`, `qaReportPath`, `releaseManifestPath`, `qualityStatus`) and adds `templateId`, `assumptions`, `missingExtensions`, and `finalReportPath`.

- [ ] **Step 1: Write failing orchestrator tests**

  Add `test_orchestrator_runs_one_sentence_web_request_to_verified_local_result`, `test_orchestrator_resume_is_idempotent`, and `test_orchestrator_blocks_external_action_without_approval`.

  Use fake runtime/trust/provisioner collaborators. Assert one project identity, one workspace, one execution plan, no external connector call, and a non-completed status when ClaimLatch or required approval is missing.

- [ ] **Step 2: Run focused tests and verify failure**

  Run: `python -m pytest tests/iseol/test_orchestrator.py -q`.

  Expected: FAIL because the orchestrator boundary does not exist.

- [ ] **Step 3: Extract the current project flow into `IseolOrchestrator`**

  Move project allocation/reuse, request context persistence, planning handoff, local provisioning, graph execution, web verification, ClaimLatch release, document handoff, and final output shaping behind the new class. Preserve current SQLite execution envelopes and background supervisor behavior. Convert `ProjectIntent` to the existing `RequestBrief` at one explicit adapter boundary; no second independent natural-language parser may remain in the execution path.

- [ ] **Step 4: Make retries and restarts idempotent**

  Reuse `resumeProjectId`, the latest request context, current project revision, and `.gleave/iseol-checkpoint.json`. Do not create a second scaffold when the current profile and revision already exist. Record a blocked/retry state instead of overwriting terminal evidence.

- [ ] **Step 5: Run focused and existing project-flow tests**

  Run: `python -m pytest tests/iseol/test_orchestrator.py tests/e2e/test_core_project_flow.py tests/e2e/test_assistant_project_runtime.py tests/project_runtime/test_project_runtime_models.py -q`.

  Expected: PASS with existing accepted-background-job and restart-recovery behavior preserved.

### Task 5: Built-in web template selection and meal-planner vertical slice

**Files:**
- Create: `apps/eeee/app/project_runtime/templates.py`
- Create: `apps/eeee/app/project_runtime/meal_planner_scaffold.py`
- Modify: `apps/eeee/app/project_runtime/provisioner.py`
- Modify: `apps/eeee/app/project_runtime/web_runner.py`
- Modify: `apps/eeee/app/workflow/planner.py`
- Test: `apps/eeee/tests/project_runtime/test_templates.py`
- Test: `apps/eeee/tests/project_runtime/test_meal_planner_scaffold.py`
- Modify: `apps/eeee/tests/project_runtime/test_web_runner.py`

**Interfaces:**
- Produces `WebTemplateCatalog.resolve(intent: ProjectIntent) -> WebTemplate`.
- Produces `MealPlannerTemplate.create(workspace: Path, project_name: str) -> list[Path]`.
- `ProjectProvisioner` chooses a core template from the intent; it does not require a plugin to generate the first local web result.
- `WebProjectRunner.prepare` validates the selected template contract rather than assuming every web project is Todo-shaped.

- [ ] **Step 1: Write failing template tests**

  Add `test_meal_request_selects_meal_planner_template` and assert generated files contain today view, breakfast/lunch/dinner grouping, add/edit/delete flow, empty/error states, local persistence, responsive viewport metadata, Korean copy, and no placeholder text.

  Add `test_generic_web_request_keeps_generic_template` so the existing web path does not regress.

- [ ] **Step 2: Run focused tests and verify failure**

  Run: `python -m pytest tests/project_runtime/test_templates.py tests/project_runtime/test_meal_planner_scaffold.py -q`.

  Expected: FAIL because only the fixed Todo-shaped web scaffold exists.

- [ ] **Step 3: Implement template selection and the meal-planner scaffold**

  Keep the template credential-free and local-first. Use the existing generated-app conventions, but make domain entities and UI copy reflect the user’s actual request. Record the template ID in `ProjectProfile`, `PROJECT_PROFILE.json`, `DESIGN.md`, and `execution-plan.json`. Also provide a `generic_web` fallback: when no built-in template matches, the connected `AgentRuntime` may implement the requested product inside the generic boundary, but only common web checks may be claimed.

- [ ] **Step 4: Generalize runner checks**

  Keep common checks for UTF-8, syntax, viewport, responsive CSS, runtime health, persistence, and truthful auth. Add template-specific checks through the template contract so the runner can later accept plugin-provided templates without hard-coded provider code. If a browser engine is unavailable, record the browser check as `not_run`; do not turn it into `PASS` or call a portfolio release fully verified.

- [ ] **Step 5: Run focused web tests and existing runner tests**

  Run: `python -m pytest tests/project_runtime/test_templates.py tests/project_runtime/test_meal_planner_scaffold.py tests/project_runtime/test_web_runner.py tests/project_runtime/test_todo_runner.py -q`.

  Expected: PASS for both the new meal slice and legacy Todo generation.

### Task 6: Whole-project quality evaluator and evidence report

**Files:**
- Create: `apps/eeee/app/iseol/review.py`
- Modify: `apps/eeee/app/iseol/quality.py`
- Modify: `apps/eeee/app/project_runtime/web_runner.py`
- Modify: `apps/eeee/app/release/manifest.py` only for report references if needed
- Test: `apps/eeee/tests/iseol/test_review.py`
- Modify: `apps/eeee/tests/iseol/test_quality.py`

**Interfaces:**
- Produces `ProjectQualityEvaluator.evaluate(workspace: Path, intent: ProjectIntent, plan: ProjectExecutionPlan, qa_report: dict[str, object] | None, claim_latch: Mapping[str, object] | None) -> FinalProjectReport`.
- Produces a 100-point score with categories from the spec: requirements 15, research/content/IA 10, UX/UI/design system 15, technical/code 20, tests/security/accessibility/performance 20, deploy/ops/recovery 10, docs/handoff/portfolio 10.
- Produces grades `portfolio_ready`, `client_ready_with_notes`, `revision_required`, and `replan_required`.
- Hard blockers include broken core flow, secret/PII exposure, missing rollback evidence, forged/missing evidence, unauthorized external resource mutation, and false completion.

- [ ] **Step 1: Write failing quality-report tests**

  Add `test_final_report_scores_required_categories`, `test_final_report_blocks_false_completion`, `test_quality_checks_replacement_characters_bom_and_diff_whitespace`, and `test_quality_report_records_missing_plugin_as_limitation_not_success`.

- [ ] **Step 2: Run focused tests and verify failure**

  Run: `python -m pytest tests/iseol/test_review.py tests/iseol/test_quality.py -q`.

  Expected: FAIL because the whole-project score and report contract do not exist.

- [ ] **Step 3: Implement deterministic evidence checks and score aggregation**

  Read files and persisted reports as evidence. Run bounded local checks only; do not infer PASS from agent prose. Verify UTF-8/replacement characters/BOM/LF, `git diff --check`, required artifacts, test result linkage, secrets, responsive/accessibility markers, browser-check availability, and ClaimLatch identity. Distinguish `PASS`, `WARN`, `BLOCK`, and `NOT_RUN`, and prevent a final release grade from reaching `portfolio_ready` when a required browser check is `NOT_RUN`.

- [ ] **Step 4: Persist `FINAL-QUALITY-REPORT.json` and link it to release output**

  Write a human-readable summary plus machine-readable fields: initial request, final result, selected graph, artifacts, requirement traceability, gate results, retries, test results, PR/CI/encoding status, security/accessibility/performance, limitations, score, grade, and next improvements.

- [ ] **Step 5: Run focused quality tests**

  Run: `python -m pytest tests/iseol/test_review.py tests/iseol/test_quality.py tests/project_runtime/test_web_runner.py -q`.

  Expected: PASS, and a report with any missing external plugin clearly marked as incomplete rather than hidden.

### Task 7: Assistant/API progress and truthful final response

**Files:**
- Modify: `apps/eeee/app/assistant/service.py`
- Modify: `apps/eeee/app/api/routes.py`
- Modify: `apps/eeee/app/project_view/service.py`
- Modify: `apps/eeee/app/desktop/plugin_presentation.py` only if output formatting requires it
- Test: `apps/eeee/tests/api/test_assistant_routes.py`
- Test: `apps/eeee/tests/api/test_project_view_routes.py`
- Test: `apps/eeee/tests/desktop/test_presentation.py`

**Interfaces:**
- `POST /api/assistant/route` remains the only user-facing start action.
- Add `GET /api/projects/{project_id}/quality` returning `FinalProjectReport` when available and a truthful `awaiting` response while running.
- Add `GET /api/projects/{project_id}/execution-plan` returning the persisted intent, selected phases, selected extensions, missing extensions, and task statuses without raw secrets.
- Assistant response adds optional `templateId`, `finalReportPath`, `qualityScore`, `qualityGrade`, and `missingExtensions` fields while retaining existing aliases.

- [ ] **Step 1: Write failing API tests**

  Assert that a one-sentence request returns `accepted` for background execution, exposes the project ID, and eventually exposes the template and final report. Assert that a running project is not presented as completed and a missing plugin appears as a limitation.

  Assert that the project view exposes phase/task progress and that no raw credential or full prompt is returned in progress payloads.

- [ ] **Step 2: Run focused API tests and verify failure**

  Run: `python -m pytest tests/api/test_assistant_routes.py tests/api/test_project_view_routes.py tests/desktop/test_presentation.py -q`.

  Expected: FAIL for the new report/plan fields and endpoints.

- [ ] **Step 3: Implement response and read-only progress endpoints**

  Reuse persisted execution envelopes and workspace reports. Keep the desktop UI non-blocking; it should display “진행 중”, “검증 대기”, “외부 연결 필요”, or “완료” based on evidence-backed state.

- [ ] **Step 4: Run focused tests and the full EEEE suite**

  Run from `apps/eeee`: `python -m pytest -q`.

  Expected: PASS with no regression in plugin OAuth, conversation history, desktop, mobile, and existing project APIs.

### Task 8: End-to-end natural-language acceptance and release verification

**Files:**
- Create: `apps/eeee/tests/e2e/test_natural_language_project_execution.py`
- Modify: `apps/eeee/scripts/check_artifacts.py` if final report validation belongs there
- Modify: `scripts/verify-core-product.ps1` to include the new acceptance command
- Modify: `apps/eeee/README.md` with the real one-sentence flow and limitations
- Create: `apps/eeee/docs/ISEOL_NATURAL_LANGUAGE_FLOW.md`

**Interfaces:**
- The acceptance test treats the public contract as `POST /api/assistant/route` → background job → project map/plan → local preview/QA → final quality report.
- The documentation must explicitly state that plugin implementations are not included yet and that external actions remain pending until those connectors are added and approved.

- [ ] **Step 1: Write the end-to-end acceptance tests**

  Add `test_one_sentence_meal_web_request_produces_local_verified_project`, `test_natural_language_request_does_not_load_unrelated_plugins`, `test_restart_resumes_same_project`, and `test_failed_agent_produces_blocked_quality_report`.

- [ ] **Step 2: Run the acceptance tests in isolation**

  Run: `python -m pytest tests/e2e/test_natural_language_project_execution.py -q`.

  Expected: PASS only after all prior tasks are implemented; failures must identify the exact phase/evidence gap.

- [ ] **Step 3: Add repository-level verification**

  Include full pytest, `git diff --check`, strict UTF-8 scan, replacement-character scan, release artifact validation, and the existing product verification scripts. Do not add auto-commit, auto-push, or auto-PR behavior; any existing local workspace recording behavior must be made explicit in the evidence and must never publish externally.

- [ ] **Step 4: Run final verification before reporting completion**

  Run:

  ```powershell
  Set-Location apps\eeee
  $env:QT_QPA_PLATFORM = "offscreen"
  python -m pytest -q
  Set-Location ..\..
  git diff --check
  powershell -ExecutionPolicy Bypass -File scripts\verify-core-product.ps1
  ```

  Expected: all commands pass, the meal web request has a final report, and any missing plugin is shown as an explicit limitation rather than a false success.

## Self-review result

- The plan covers the spec’s natural-language intake, dynamic organization, plugin boundary, local project execution, quality scoring, evidence, progress UI, idempotency, and final report sections.
- Plugin implementations are intentionally absent; only manifest/selection contracts are added.
- Existing EEEE routes, background jobs, SQLite execution ledger, ClaimLatch, Todo runner, and generic web runner are preserved through compatibility tests.
- The five review-focus failure modes each have an owning task and named test.
- No step authorizes external account/resource mutation, commit, push, or PR creation.
- The plan now makes `ProjectIntent` the single natural-language source, keeps `RequestBrief` as a compatibility adapter, makes the Python graph compiler authoritative for native execution, and distinguishes generic-web verification from template-specific verification.
