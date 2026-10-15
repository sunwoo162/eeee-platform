# EEEE Growth Web GPT Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make EEEE a growth-oriented assistant core with explicit Web GPT selection, verified provider failure handling, and user-approved memory feedback.

**Architecture:** Keep one EEEE Core and SQLite source of truth. A provider selector chooses Web GPT or Ollama for the existing conversation service; the desktop and future Chat History plugin continue to consume the same API. Growth signals are stored separately from active memory, and only explicit user-approved feedback is promoted into bounded conversation context.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, pytest, existing `ChatGptWebRuntime` and `OllamaRuntime` adapters.

**Spec:** `docs/superpowers/specs/2026-10-15-eeee-growth-webgpt-design.md`

## Global Constraints

- Preserve existing project, request, conversation, and memory data.
- Never silently convert provider failure into a completed assistant answer.
- `auto` may select Web GPT only when the bridge is ready; explicit `chatgpt_web` never falls back to Ollama.
- Raw conversation and unapproved feedback never become active memory.
- Do not modify Chat History plugin or ISEOL internals in this plan.
- Keep provider credentials out of messages, events, and feedback payloads.

## Review Focus

- Web GPT configured but bridge unavailable: explicit provider selection must fail truthfully without Ollama fallback.
- Provider yields no deltas: request must be failed, not completed with an empty answer.
- Multiple active memories and a long transcript: context must stay bounded and exclude revoked/superseded records.
- `remember=true` without correction/source: promotion must be rejected without partial writes.
- Duplicate feedback submission: feedback IDs and memory promotion must remain idempotent.

---

### Task 1: Provider selection and Web GPT conversation adapter

**Files:**
- Create: `apps/eeee/app/conversations/providers.py`
- Modify: `apps/eeee/app/config.py`
- Modify: `apps/eeee/app/main.py`
- Modify: `apps/eeee/app/api/conversation_routes.py`
- Modify: `apps/eeee/.env.example`
- Test: `apps/eeee/tests/conversations/test_providers.py`
- Test: `apps/eeee/tests/core/test_paths.py`
- Test: `apps/eeee/tests/api/test_conversation_routes.py`

**Interfaces:**
- Produces `ConversationProviderSelection`, `build_conversation_provider(...)`, and a `ChatGptWebConversationProvider` implementing `ConversationProvider.stream(...)`.
- Produces a provider status payload with selected provider, configured providers, and truthful readiness.

- [ ] **Step 1: Write failing provider-selection and Web adapter tests**

Test `auto` chooses Web GPT when configured, explicit Web GPT does not fall back, Ollama selection remains available, and Web adapter forwards bounded context and yields the assistant text.

- [ ] **Step 2: Run the focused tests and verify the expected failures**

Run: `python -m pytest tests/conversations/test_providers.py tests/core/test_paths.py -q`

Expected: FAIL because the provider selector, setting, and Web adapter do not exist.

- [ ] **Step 3: Implement provider selection and configuration**

Add `conversation_provider: Literal["auto", "chatgpt_web", "ollama"]` with `auto` as the compatibility-aware default, create the Web adapter and truthful unavailable provider, and construct the selected provider once in `create_app()` before `ConversationService` is built.

- [ ] **Step 4: Update runtime status and integration tests**

Keep the existing `ollama` status for compatibility while adding `conversationProvider` and `providers` fields. Verify injected test providers remain supported.

- [ ] **Step 5: Run focused tests and commit**

Run: `python -m pytest tests/conversations/test_providers.py tests/core/test_paths.py tests/api/test_conversation_routes.py -q`

Expected: PASS with no new warnings.

Commit: `feat: add selectable Web GPT conversation provider`

### Task 2: Provider response quality gate

**Files:**
- Modify: `apps/eeee/app/conversations/service.py`
- Modify: `apps/eeee/app/conversations/models.py` if a typed error/status is needed
- Test: `apps/eeee/tests/conversations/test_service.py`

**Interfaces:**
- Consumes the selected `ConversationProvider` from Task 1.
- Produces a terminal failure with `provider_empty_response` when the provider emits no meaningful text.

- [ ] **Step 1: Write the failing empty-response regression test**

Assert that a provider yielding no deltas creates a failed assistant message and failed request event, never a completed empty message.

- [ ] **Step 2: Run the regression test and verify it fails**

Run: `python -m pytest tests/conversations/test_service.py -k empty_response -q`

Expected: FAIL because the current service completes an empty assistant message.

- [ ] **Step 3: Implement the minimal quality gate**

Raise a typed provider error after the stream if `collected.strip()` is empty, preserve cancellation semantics, and map only provider cancellation codes to cancelled state.

- [ ] **Step 4: Run the focused conversation suite**

Run: `python -m pytest tests/conversations/test_service.py tests/api/test_request_flow.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit: `fix: fail empty assistant responses truthfully`

### Task 3: Growth feedback ledger and explicit memory promotion

**Files:**
- Modify: `apps/eeee/app/memory/models.py`
- Modify: `apps/eeee/app/memory/store.py`
- Create: `apps/eeee/app/assistant/growth.py`
- Modify: `apps/eeee/app/api/routes.py`
- Test: `apps/eeee/tests/memory/test_growth_feedback.py`
- Test: `apps/eeee/tests/api/test_memory_api.py`

**Interfaces:**
- Produces `GrowthService.record_feedback(...)` and `GrowthFeedback` data returned by `POST /api/memory/feedback`.
- `remember=true` with a correction creates one explicit, user-editable `agent_routing_hint` memory linked to the source message and feedback evidence.

- [ ] **Step 1: Write failing ledger and promotion tests**

Cover feedback persistence, restart visibility, rejection of `remember=true` without correction, no auto-promotion for ordinary feedback, explicit promotion idempotency, and secret redaction.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest tests/memory/test_growth_feedback.py tests/api/test_memory_api.py -k feedback -q`

Expected: FAIL because the feedback model, table, service, and endpoint do not exist.

- [ ] **Step 3: Implement the feedback table and service**

Add an idempotent `assistant_feedback` table in the existing memory store, persist only bounded/redacted fields, and use `save_explicit_memory` for the explicit `remember=true` path.

- [ ] **Step 4: Add the API contract**

Add request/response models and `POST /api/memory/feedback`; return the feedback ID and optional memory record without exposing provider credentials or raw secrets.

- [ ] **Step 5: Run the focused memory/API suite and commit**

Run: `python -m pytest tests/memory/test_growth_feedback.py tests/api/test_memory_api.py -q`

Expected: PASS.

Commit: `feat: persist growth feedback with explicit memory promotion`

### Task 4: Feed approved growth memory into conversation context

**Files:**
- Modify: `apps/eeee/app/conversations/context.py`
- Modify: `apps/eeee/app/main.py`
- Test: `apps/eeee/tests/conversations/test_context.py`
- Test: `apps/eeee/tests/memory/test_conversation_boundary.py`

**Interfaces:**
- Consumes active `MemoryStore` records from Task 3.
- Produces bounded system context containing eligible active memory before transcript messages.

- [ ] **Step 1: Write failing context tests**

Assert active explicit memory is included, revoked and superseded memory are excluded, raw conversation turns are not promoted, and the combined context remains within the configured character budget.

- [ ] **Step 2: Run focused tests and verify the intended failures**

Run: `python -m pytest tests/conversations/test_context.py tests/memory/test_conversation_boundary.py -q`

Expected: FAIL for automatic active-memory inclusion because the production builder currently receives no memory store.

- [ ] **Step 3: Implement bounded memory retrieval and wiring**

Wire the coordinator-owned `MemoryStore` into the conversation context builder, select only active non-expired records, reserve budget for transcript, and preserve the existing explicit `memory_ids` behavior.

- [ ] **Step 4: Run focused tests and commit**

Run: `python -m pytest tests/conversations/test_context.py tests/memory/test_conversation_boundary.py tests/conversations/test_service.py -q`

Expected: PASS.

Commit: `feat: apply approved growth memory to conversation context`

### Task 5: Whole-branch verification and review

**Files:**
- Modify: `docs/superpowers/verification/2026-10-15-eeee-v1-acceptance.md` if evidence changes
- Modify: `apps/eeee/README.md` with provider and feedback configuration
- Test: full `apps/eeee/tests` suite

- [ ] **Step 1: Run the focused growth/provider suite**

Run the tests from Tasks 1–4 and record exact counts.

- [ ] **Step 2: Run the full deterministic suite**

Run: `python -m pytest tests -q`

Expected: zero failures; warnings are reported exactly.

- [ ] **Step 3: Run live provider checks only when configured**

Run the existing local/Web smoke scripts. If a provider or authenticated bridge is unavailable, record `blocked` or `not run`, never a fake pass.

- [ ] **Step 4: Request a fresh whole-branch code review**

Review the diff against the spec, with special attention to fallback policy, memory contamination, provider errors, idempotency, and credential redaction.

- [ ] **Step 5: Fix Critical/Important findings with RED→GREEN tests and rerun the full suite**

- [ ] **Step 6: Commit documentation/evidence and leave the branch ready for the user’s chosen integration action**
