# EEEE Hybrid Memory Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development) to implement this plan task-by-task.

**Goal:** Connect EEEE's persistent personalized memory to a local-first/provider-fallback runtime policy without weakening ISEOL or ClaimLatch gates.

**Architecture:** Add a small provider-policy module and a bounded memory-context compiler. Keep `MemoryStore` as the canonical local ledger, pass compiled context through `GeneralConversationCapability`, and wire local-first/general-Web-fallback in `main.py`; project execution remains on the existing ISEOL runtime path.

**Tech Stack:** Python 3, Pydantic, SQLite, FastAPI, existing AgentRuntime adapters, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-eeee-hybrid-memory-routing-design.md`

## Global Constraints

- EEEE owns canonical memory; providers do not persist independent memory.
- Remote providers receive bounded relevant context only.
- Secrets and credentials must not enter provider context.
- Existing ClaimLatch/QA release gates remain unchanged.
- Existing user changes and unrelated dirty files must be preserved.

## Review Focus

- Local model missing: general chat must use Web fallback or truthful unavailable status.
- Web-only project routing: must not silently become a fake local success.
- Sensitive preference values: must be excluded from provider packets.
- Reopened process: memory must survive and be usable by either provider.
- Existing runtime injection tests: custom runtimes must keep working.

### Task 1: Bounded memory context compiler

**Files:** Create `apps/eeee/app/memory/context.py`; Test `apps/eeee/tests/memory/test_memory_context.py`.

- [x] Write failing tests for relevant active records, preference inclusion, limit, and secret exclusion.
- [x] Run the focused tests and confirm the expected missing-module failure.
- [x] Implement `MemoryContextPacket` and `MemoryContextCompiler.compile(query, store, limit=12)`.
- [x] Run focused tests and then the memory suite.

### Task 2: Provider routing policy

**Files:** Create `apps/eeee/app/agent/provider_policy.py`; Test `apps/eeee/tests/agent/test_provider_policy.py`.

- [x] Write failing tests for local-first simple requests, Web-preferred project requests, and unavailable fallback.
- [x] Implement deterministic request classification and provider choice.
- [x] Run focused tests.

### Task 3: General conversation integration

**Files:** Modify `apps/eeee/app/kernel/capabilities.py`, `apps/eeee/app/kernel/service.py`; Test `apps/eeee/tests/assistant/test_assistant_service.py`.

- [x] Add tests proving compiled preference content is included while IDs remain available.
- [x] Pass the compiler output into the runtime prompt and preserve custom runtime behavior.
- [x] Run assistant and memory suites.

### Task 4: Local-first/Web fallback wiring

**Files:** Create `apps/eeee/app/agent/hybrid_runtime.py`; Modify `apps/eeee/app/main.py`; Test `apps/eeee/tests/agent/test_hybrid_runtime.py`.

- [x] Write failing tests for local success, local unavailable then Web fallback, and complex request Web preference.
- [x] Implement one serialized hybrid runtime for general assistant messages only.
- [x] Keep the existing ISEOL project runtime selection unchanged.
- [x] Run focused tests and the full EEEE suite.

### Task 5: Verification and documentation

- [x] Run `pytest` for `apps/eeee` and the repository verification script.
- [x] Inspect `git diff` for scope and preserve unrelated changes.
- [x] Report exact passing counts and any live Web limitation without claiming unverified success.
