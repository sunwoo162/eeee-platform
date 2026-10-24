# EEEE Personal LLM Provider Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended for this task). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect EEEE's conversation lane to the completed `eeee-personal-llm` loopback service as the default local provider while preserving explicit ChatGPT Web and Ollama providers.

**Architecture:** Add a small HTTP runtime adapter in EEEE that speaks the personal LLM's typed `/v1/chat` and status contracts. Extend the existing provider-selection and conversation-service contracts with optional request/conversation IDs, so the adapter can preserve user scope and provenance without changing legacy providers. Keep the personal LLM repository, model registry, adapter files, and SQLite database independent.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, httpx, pytest, existing EEEE conversation/provider abstractions.

**Spec:** `docs/superpowers/specs/2026-10-25-personal-llm-eeee-integration-design.ko.md`

## Global Constraints

- Do not copy or vendor code from `eeee-personal-llm` into EEEE.
- The default provider is `personal_llm`; ChatGPT Web and Ollama remain explicitly selectable.
- Do not silently forward personal conversations to ChatGPT Web when the personal LLM is unavailable.
- Use `http://127.0.0.1:8765` as the default personal LLM base URL.
- Pass EEEE's user ID in both `userId` and `X-Personal-User-Id`.
- Keep `profileRevision=0` and `approvedMemoryIds=[]` for the first integration slice; profile/memory synchronization is deferred.
- Treat timeout, connection failure, HTTP error, malformed response, and empty response as provider failures.
- Do not add personal LLM process lifecycle management or direct UI-to-model calls in this change.

## Review Focus

- A ready personal LLM must receive the exact EEEE user, request, conversation, and context message values; pin this in the runtime adapter tests.
- An unavailable personal LLM must not cause an implicit ChatGPT Web request; pin this in provider-selection tests.
- A response for another user must be rejected before persistence; pin the user-scope test in the runtime adapter.
- A slow/cancelled response must not become a completed assistant message; pin this in the provider and conversation-service tests.
- A malformed or empty typed response must fail closed with a stable provider error code; pin this in runtime tests.

## File Map

- `apps/eeee/app/agent/personal_llm_runtime.py`: loopback HTTP status and chat adapter; owns request/response parsing and transport error codes.
- `apps/eeee/app/config.py`: personal LLM URL, timeout settings, and `personal_llm` provider literal.
- `apps/eeee/app/conversations/providers.py`: `PersonalLlmConversationProvider`, builtin fallback wrapper, and provider selection wiring.
- `apps/eeee/app/conversations/service.py`: pass request and conversation IDs through the provider boundary while retaining legacy-provider compatibility.
- `apps/eeee/app/main.py`: construct the personal LLM runtime and pass it into provider selection; expose it on application state.
- `apps/eeee/app/api/conversation_routes.py`: report personal LLM status/model in `/v1/runtime`.
- `apps/eeee/tests/agent/test_personal_llm_runtime.py`: adapter contract, status, error, user scope, and cancellation tests.
- `apps/eeee/tests/conversations/test_providers.py`: provider selection and fallback tests.
- `apps/eeee/tests/conversations/test_service.py`: request/conversation ID propagation and late cancellation behavior.
- `apps/eeee/tests/core/test_paths.py`: default and environment-backed settings tests.
- `apps/eeee/tests/api/test_conversation_routes.py`: runtime status payload tests.
- `apps/eeee/.env.example`: local configuration example.
- `apps/eeee/README.md` and `docs/operations/local-runtime.md`: startup and troubleshooting instructions.

### Task 1: Add the Personal LLM HTTP runtime adapter

**Files:**
- Create: `apps/eeee/app/agent/personal_llm_runtime.py`
- Test: `apps/eeee/tests/agent/test_personal_llm_runtime.py`

**Interfaces:**
- Produces `PersonalLlmStatus(status: str, model: str | None, error_code: str | None = None, message: str | None = None)`.
- Produces `PersonalLlmRuntime(base_url, connect_timeout_seconds, generation_timeout_seconds, transport=None)` with `status() -> PersonalLlmStatus` and `chat(messages, *, user_id, request_id, conversation_id, cancel_event=None) -> str`.
- `chat()` POSTs to `/v1/chat` with `requestId`, `userId`, `mode="assistant"`, `profileRevision=0`, `conversationId`, `messages`, and `approvedMemoryIds=[]`, and sends `X-Personal-User-Id`.

- [ ] **Step 1: Write failing adapter tests**

  Add fake `httpx` transport tests for: ready status/model discovery; exact chat payload and user header; HTTP error code mapping; malformed JSON; empty text; user ID mismatch; timeout; and cancellation before/after the request.

- [ ] **Step 2: Run the focused tests to verify they fail**

  Run: `python -m pytest apps/eeee/tests/agent/test_personal_llm_runtime.py -q`

  Expected: FAIL because the runtime module and contract types do not exist.

- [ ] **Step 3: Implement the runtime adapter**

  Use `httpx.Client` with separate connect and generation timeouts. Validate status payloads and the camelCase `ChatResponse` fields explicitly enough to reject non-object, malformed, wrong-user, failed-status, and empty-text responses. Raise a dedicated `PersonalLlmRuntimeError` carrying stable codes such as `personal_llm_unavailable`, `personal_llm_timeout`, `personal_llm_invalid_response`, `personal_llm_empty_response`, and `conversation_cancelled`.

- [ ] **Step 4: Run the focused tests to verify they pass**

  Run: `python -m pytest apps/eeee/tests/agent/test_personal_llm_runtime.py -q`

  Expected: all adapter tests pass.

- [ ] **Step 5: Commit the runtime boundary**

  ```powershell
  git add apps/eeee/app/agent/personal_llm_runtime.py apps/eeee/tests/agent/test_personal_llm_runtime.py
  git commit -m "feat: add personal LLM runtime adapter"
  ```

### Task 2: Wire configuration and provider selection

**Files:**
- Modify: `apps/eeee/app/config.py`
- Modify: `apps/eeee/app/conversations/providers.py`
- Modify: `apps/eeee/app/conversations/service.py`
- Test: `apps/eeee/tests/conversations/test_providers.py`
- Test: `apps/eeee/tests/conversations/test_service.py`
- Test: `apps/eeee/tests/core/test_paths.py`

**Interfaces:**
- `Settings.conversation_provider` accepts `"auto" | "personal_llm" | "chatgpt_web" | "ollama"` and defaults to `"personal_llm"`.
- `Settings.personal_llm_base_url`, `personal_llm_connect_timeout_seconds`, and `personal_llm_generation_timeout_seconds` default to `http://127.0.0.1:8765`, `3.0`, and `120.0`.
- `build_conversation_provider(..., personal_llm: PersonalLlmRuntime | None = None, ...)` returns `ConversationProviderSelection` with provider name `personal_llm`, status, model, reason, and optional builtin fallback.
- `ConversationProvider.stream()` gains optional `request_id: str | None` and `conversation_id: str | None` keyword arguments; existing providers continue to work through the compatibility fallback.

- [ ] **Step 1: Write failing configuration and selection tests**

  Add tests proving the new defaults/env aliases, positive timeout validation, explicit ready personal provider selection, explicit unavailable personal provider behavior, auto preference for ready personal LLM, no silent Web fallback, and preservation of existing Web/Ollama selection when personal LLM is not supplied to the factory.

- [ ] **Step 2: Write failing service propagation tests**

  Add a recording provider that accepts the new keywords and assert `ConversationService.run_request()` passes the stored request ID, conversation ID, and user ID. Add a legacy provider test proving providers without the new keywords still run.

- [ ] **Step 3: Run focused tests to verify they fail**

  Run: `python -m pytest apps/eeee/tests/conversations/test_providers.py apps/eeee/tests/conversations/test_service.py apps/eeee/tests/core/test_paths.py -q`

  Expected: FAIL on the new provider/configuration/propagation assertions.

- [ ] **Step 4: Implement settings and provider integration**

  Add `PersonalLlmConversationProvider` that rechecks runtime status at request time, maps runtime errors to `ConversationProviderError`, records `active_provider_name="personal_llm"` and the active model, and yields one complete answer. Add a personal-LLM builtin fallback wrapper matching the existing bounded fallback policy. Extend selection so `auto` chooses ready personal LLM first and never silently selects ChatGPT Web after a personal LLM failure. Update `ConversationService` and helper calls to pass request/conversation IDs while catching only the expected legacy `TypeError` compatibility case.

- [ ] **Step 5: Run focused tests to verify they pass**

  Run: `python -m pytest apps/eeee/tests/conversations/test_providers.py apps/eeee/tests/conversations/test_service.py apps/eeee/tests/core/test_paths.py -q`

  Expected: all existing and new provider/service/settings tests pass.

- [ ] **Step 6: Commit the provider wiring**

  ```powershell
  git add apps/eeee/app/config.py apps/eeee/app/conversations/providers.py apps/eeee/app/conversations/service.py apps/eeee/tests/conversations/test_providers.py apps/eeee/tests/conversations/test_service.py apps/eeee/tests/core/test_paths.py
  git commit -m "feat: route EEEE conversations through personal LLM"
  ```

### Task 3: Construct the provider in EEEE and expose runtime status

**Files:**
- Modify: `apps/eeee/app/main.py`
- Modify: `apps/eeee/app/api/conversation_routes.py`
- Test: `apps/eeee/tests/api/test_conversation_routes.py`

**Interfaces:**
- `create_app()` constructs `PersonalLlmRuntime` from `Settings` and passes it to `build_conversation_provider`.
- `application.state.personal_llm_runtime` contains the constructed runtime.
- `GET /v1/runtime` returns `providers.personal_llm.status` and `providers.personal_llm.model`, and the selected provider fields report the same `personal_llm` identity.

- [ ] **Step 1: Write failing app wiring/status tests**

  Add a fake transport/status test through `create_app(Settings(...), ...)` or the existing dependency injection seam. Assert the selected provider is `personal_llm` when the local service is ready, and assert `/v1/runtime` includes the personal provider status/model without removing the existing Ollama and ChatGPT Web entries.

- [ ] **Step 2: Run the focused API tests to verify they fail**

  Run: `python -m pytest apps/eeee/tests/api/test_conversation_routes.py -q`

  Expected: FAIL because EEEE does not construct or report the personal runtime.

- [ ] **Step 3: Implement app construction and runtime reporting**

  Instantiate the runtime beside `OllamaRuntime`, pass it into provider selection, store it on `application.state`, and extend the route's selected-status calculation only for `personal_llm`. Preserve the existing injected-provider behavior used by tests.

- [ ] **Step 4: Run the focused API tests to verify they pass**

  Run: `python -m pytest apps/eeee/tests/api/test_conversation_routes.py -q`

  Expected: all conversation route tests pass.

- [ ] **Step 5: Commit app wiring**

  ```powershell
  git add apps/eeee/app/main.py apps/eeee/app/api/conversation_routes.py apps/eeee/tests/api/test_conversation_routes.py
  git commit -m "feat: expose personal LLM runtime in EEEE"
  ```

### Task 4: Document local operation and run end-to-end verification

**Files:**
- Modify: `apps/eeee/.env.example`
- Modify: `apps/eeee/README.md`
- Modify: `docs/operations/local-runtime.md`
- Test: `apps/eeee/tests/core/test_paths.py`

**Interfaces:**
- Documentation describes starting `eeee-personal-llm` separately with its configured active adapter and then starting EEEE with `EEEE_CONVERSATION_PROVIDER=personal_llm`.
- Documentation states that EEEE talks to the loopback `/v1/chat` API and does not automatically send the conversation to ChatGPT Web.

- [ ] **Step 1: Add configuration examples and documentation**

  Set the example provider to `personal_llm`, document the three new environment variables, identify the default port, and add troubleshooting for `/health`, `/v1/model/status`, unavailable model, and explicit provider switching.

- [ ] **Step 2: Run formatting and focused regression checks**

  Run: `python -m pytest apps/eeee/tests/agent/test_personal_llm_runtime.py apps/eeee/tests/conversations/test_providers.py apps/eeee/tests/conversations/test_service.py apps/eeee/tests/api/test_conversation_routes.py apps/eeee/tests/core/test_paths.py -q`

  Expected: all focused tests pass.

- [ ] **Step 3: Run the EEEE core verification**

  Run: `powershell -ExecutionPolicy Bypass -File scripts/verify-core-product.ps1`

  Expected: the core verification completes successfully with no new failures.

- [ ] **Step 4: Run an actual loopback smoke when the personal LLM service is available**

  Start the completed service from `C:\Users\user\Documents\eeee-personal-llm-project` with its active registry adapter, start EEEE with `EEEE_CONVERSATION_PROVIDER=personal_llm`, call `/v1/runtime`, create a conversation, send one Korean turn, and verify the stored assistant message has provider `personal_llm` and a non-empty model version. Stop only processes started for this smoke.

- [ ] **Step 5: Run repository hygiene checks and inspect the final diff**

  Run: `git diff --check; git status --short; git diff --stat`

  Expected: only the intended EEEE source/tests/docs are changed; no model artifacts, databases, logs, or generated workspaces are added.

- [ ] **Step 6: Commit documentation and verified integration**

  ```powershell
  git add apps/eeee/.env.example apps/eeee/README.md docs/operations/local-runtime.md
  git commit -m "docs: document EEEE personal LLM integration"
  ```

## Self-Review

- Spec coverage: provider adapter, default selection, request/user mapping, provenance, fail-closed errors, no implicit external fallback, status reporting, docs, and smoke verification are covered by Tasks 1–4.
- Type consistency: `PersonalLlmRuntime.chat()` receives request and conversation IDs; the provider boundary forwards those optional keywords; legacy providers remain compatible through the existing TypeError fallback pattern.
- Review focus coverage: exact payload and user header are Task 1; no Web fallback is Task 2; cancellation and late responses are Tasks 1–2; malformed/empty responses are Task 1.
- Proportion: the plan changes only the existing provider boundary and adds one focused runtime module; it does not redesign EEEE memory, UI, or the independent personal LLM service.
