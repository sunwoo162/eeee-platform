# Iseol IMPLEMENT PATCH_FRAME_V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal**
Replace fragile IMPLEMENT JSON patch transport with strict stage-aware PATCH_FRAME_V1 while preserving all validation and recovery safety.

**Architecture**
The reasoning executor selects an explicit contract per Harness stage. IMPLEMENT responses use an exact first-line frame and raw EOF diff payload; other stages retain strict JSON. The extracted diff is validated by the existing unified-diff and Desktop intent pipelines before dispatch.

**Tech Stack**
TypeScript, Node.js ESM, tsx, Node test runner, Playwright Core, WebSocket Desktop Agent transport, filesystem JSON/JSONL stores.

**Spec**
`docs/superpowers/specs/2026-09-17-iseol-implement-patch-frame-v1-design.md`

**Global Constraints**
No permissive parsing, malformed-output repair, patch repair, retry/budget/timeout increases, safety-boundary weakening, raw model-content persistence, credential access, PR/merge, live smoke during implementation, or Tasks 2–10 work. JSON.parse remains authoritative for JSON stages; no unvalidated patch may reach Desktop.

## File map

- `src/chatgpt-web/contracts.ts` — reasoning/intent contracts and exact-key assertions.
- `src/chatgpt-web/prompt-compiler.ts` — initial stage output contract and prompts.
- `src/chatgpt-web/web-reasoning-executor.ts` — stage execution, correction prompts, and retry handling.
- `src/chatgpt-web/playwright-browser-driver.ts` — assistant extraction, stage-aware result parsing, legacy appendix reader, strict diff validation, safe diagnostics.
- `src/chatgpt-web/browser-adapter.ts` — browser result/error interfaces.
- `src/chatgpt-web/production-browser-adapter.ts` — production correlation and parser-diagnostic persistence.
- `src/chatgpt-web/intent-compiler.ts` — conversion of validated intents to Desktop operations.
- `src/idea-lab/production-runtime-driver.ts` — IMPLEMENT semantic stage and internal intent ownership.
- `src/idea-lab/production-desktop-compiler.ts` — Desktop task-pack construction and validation inputs.
- `tests/chatgpt-web-playwright-driver.test.ts` — parser and browser extraction regressions.
- `tests/chatgpt-web-prompt-compiler.test.ts` — output contract/prompt tests.
- `tests/chatgpt-web-reasoning-executor.test.ts` — correction/recovery tests.
- `tests/chatgpt-web-contracts.test.ts` and `tests/chatgpt-web-intent-compiler.test.ts` — schema and Desktop validation.
- `tests/idea-lab-production-runtime-driver.test.ts` and `tests/idea-lab-production-desktop-compiler.test.ts` — production integration.

## Task 1 — Explicit stage result-contract selection

**Files:** `src/chatgpt-web/web-reasoning-executor.ts`, `src/chatgpt-web/browser-adapter.ts`, `src/chatgpt-web/playwright-browser-driver.ts`, `tests/chatgpt-web-reasoning-executor.test.ts`, `tests/chatgpt-web-playwright-driver.test.ts`.

**Interfaces:** Add `"structured-json" | "patch-frame-v1"` stage contract type; thread it through `awaitStructuredResult` input and executor calls. IMPLEMENT selects `patch-frame-v1`; CONTEXT/ANALYZE/PLAN select JSON.

**RED:** Add a test passing an IMPLEMENT frame to the current JSON path and assert rejection, plus tests proving non-IMPLEMENT stages remain JSON. Run `node --import tsx --test tests/chatgpt-web-reasoning-executor.test.ts tests/chatgpt-web-playwright-driver.test.ts`; expect missing contract support.

**GREEN:** Thread the explicit contract without content sniffing; keep legacy call defaults only for explicitly legacy persisted sessions. Re-run the same command; all new and existing tests pass.

**Commit:** `git commit -am "feat: select stage result contracts"`

## Task 2 — Strict PATCH_FRAME_V1 parser

**Files:** `src/chatgpt-web/playwright-browser-driver.ts`, `tests/chatgpt-web-playwright-driver.test.ts`.

**Interfaces:** Add `parsePatchFrameV1(text: string): string` and bounded frame diagnostics. Header is exact `ISEOL_PATCH_V1`, payload is bytes after first newline through EOF.

**RED:** Cover exact header, missing/leading prose/empty payload, multiline content with quotes/backslashes/braces/brackets and literal header lines, trailing prose, CRLF/LF policy, and bounded diagnostics. Run the parser test file; expect parser API/behavior failures.

**GREEN:** Implement exact first-line framing and existing newline normalization only. Do not alter unified-diff validation or repair content. Run parser tests again.

**Commit:** `git commit -am "feat: parse implement patch frames"`

## Task 3 — IMPLEMENT prompts and corrections

**Files:** `src/chatgpt-web/prompt-compiler.ts`, `src/chatgpt-web/web-reasoning-executor.ts`, `tests/chatgpt-web-prompt-compiler.test.ts`, `tests/chatgpt-web-reasoning-executor.test.ts`.

**Interfaces:** Replace IMPLEMENT output instructions and correction constant with the exact PATCH_FRAME_V1 contract; remove new JSON intent/type/patchText and appendix instructions. Leave other stage prompts unchanged.

**RED:** Assert initial and correction IMPLEMENT prompts contain the exact header/EOF rules and no JSON `patchText` or legacy appendix language; assert CONTEXT/ANALYZE/PLAN contracts remain JSON. Run prompt/reasoning tests and observe old-contract failures.

**GREEN:** Update compiler and correction text only. Run `node --import tsx --test tests/chatgpt-web-prompt-compiler.test.ts tests/chatgpt-web-reasoning-executor.test.ts`.

**Commit:** `git commit -am "fix: request implement patch frames"`

## Task 4 — Stage-aware browser extraction and compatibility

**Files:** `src/chatgpt-web/browser-adapter.ts`, `src/chatgpt-web/production-browser-adapter.ts`, `src/chatgpt-web/playwright-browser-driver.ts`, `tests/chatgpt-web-browser-service.test.ts`, `tests/chatgpt-web-playwright-driver.test.ts`.

**Interfaces:** Pass the selected contract into browser result reads. JSON stages invoke existing parser; IMPLEMENT invokes `parsePatchFrameV1`. Legacy structured `patchText` and appendix are readable only when an explicit persisted legacy contract is supplied.

**RED:** Test patch frames rejected in non-IMPLEMENT, JSON not guessed from frame content, and legacy fixtures accepted only through explicit compatibility. Run browser/parser tests; expect routing failures.

**GREEN:** Implement explicit dispatch and bounded legacy branch. No global fallback based on response contents. Run targeted browser tests.

**Commit:** `git commit -am "fix: route stage-aware web results"`

## Task 5 — Validation and internal PROPOSE_PATCH construction

**Files:** `src/idea-lab/production-runtime-driver.ts`, `src/chatgpt-web/intent-compiler.ts`, `src/idea-lab/production-desktop-compiler.ts`, `tests/chatgpt-web-intent-compiler.test.ts`, `tests/idea-lab-production-runtime-driver.test.ts`, `tests/idea-lab-production-desktop-compiler.test.ts`.

**Interfaces:** Convert validated IMPLEMENT frame payload into runtime-owned PROPOSE_PATCH intent; retain existing path/header/hunk/count/apply validation and Desktop exact-key checks.

**RED:** Assert valid extracted patch reaches dispatch unchanged (after allowed newline normalization), while malformed frame/patch never dispatches and Desktop validation still executes. Run the three targeted test files; expect missing conversion.

**GREEN:** Construct only after strict validation, then use existing intent compiler and Desktop task compiler. Run the same command.

**Commit:** `git commit -am "fix: build patch intents after validation"`

## Task 6 — Recovery, diagnostics, and migration

**Files:** `src/chatgpt-web/web-reasoning-executor.ts`, `src/chatgpt-web/production-browser-adapter.ts`, `src/chatgpt-web/playwright-browser-driver.ts`, `tests/chatgpt-web-recovery.test.ts`, `tests/chatgpt-web-reasoning-executor.test.ts`.

**Interfaces:** Add contract-aware safe diagnostic categories for frame failures versus strict patch failures; preserve bounded retry ownership and legacy persisted-session selection.

**RED:** Assert malformed new frames request PATCH_FRAME_V1 again, diagnostics contain no patch body, legacy sessions remain bounded, budgets are unchanged, and restart does not reinterpret contracts. Run reasoning/recovery tests; expect failures.

**GREEN:** Add only metadata propagation and contract-aware correction/recovery. Run targeted recovery tests.

**Commit:** `git commit -am "fix: preserve patch frame recovery safety"`

## Task 7 — Integrated IMPLEMENT flow regression

**Files:** `tests/chatgpt-web-e2e.test.ts`, `tests/idea-lab-e2e.test.ts`, `tests/chatgpt-web-playwright-driver.test.ts`.

**Interfaces:** Exercise `IMPLEMENT → PATCH_FRAME_V1 → strict validator → runtime PROPOSE_PATCH → Desktop validation/dispatch`.

**RED:** Add valid and malformed frame scenarios, including trailing prose, marker-like payload text, unsafe paths, bad hunk counts, and exact dispatched patch equality. Run the focused E2E files; expect old JSON transport failures.

**GREEN:** Update fixtures and integration wiring; verify invalid frames stop before dispatch and non-IMPLEMENT JSON remains unchanged.

**Commit:** `git commit -am "test: cover implement patch frame flow"`

## Task 8 — Verification and smoke readiness

**Files:** affected tests only; no production changes unless verification exposes a deterministic defect.

Run:

- `node --import tsx --test tests/chatgpt-web-playwright-driver.test.ts tests/chatgpt-web-prompt-compiler.test.ts tests/chatgpt-web-reasoning-executor.test.ts tests/chatgpt-web-recovery.test.ts tests/chatgpt-web-browser-service.test.ts tests/chatgpt-web-contracts.test.ts tests/chatgpt-web-intent-compiler.test.ts tests/idea-lab-production-runtime-driver.test.ts tests/idea-lab-production-desktop-compiler.test.ts tests/chatgpt-web-e2e.test.ts tests/idea-lab-e2e.test.ts`
- `npm test`
- `npm run build`
- `git diff --check`

Expected result: all targeted tests and the full backend suite pass, TypeScript builds cleanly, and diff check is clean. Do not run live smoke in implementation iterations.

Only after these gates, run exactly one topology-controlled normal-user smoke. Acceptance requires smoke-owned Agent health, completion through IMPLEMENT with PATCH_FRAME_V1 and strict validation, PROPOSE_PATCH dispatch, one candidate, restart identity verification, `restart=verified`, and `EXIT_CODE=0`. If it fails, inspect that single root and create a RED regression before any production change.
