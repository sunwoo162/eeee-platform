# Mobile Event Gap Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the Desktop↔Mobile event contract explicitly report when a client cursor is older than the retained event window.

**Architecture:** Keep the Desktop `MobileBridge` as the source of truth. `events_after()` will compare the requested cursor with the oldest retained durable cursor and return gap metadata; the typed mobile client will expose that metadata without changing the existing event list shape.

**Tech Stack:** Python, SQLite, FastAPI-compatible dictionaries, TypeScript client, pytest, node:test.

**Spec:** `docs/superpowers/specs/2026-10-15-eeee-core-redesign-design.md`

## Global Constraints

- The Desktop remains authoritative; the mobile client must not invent missing events.
- Existing `cursor` and `events` response fields remain backward compatible.
- Retained-event limits remain enforced by `MobileBridge.event_limit`.
- No plugin implementation is added in this task.

## Review Focus

- A cursor older than the retained window must report a gap instead of silently returning a partial history.
- A fresh cursor of zero must be allowed to consume the retained window without being marked as a gap.
- An empty event table must return a stable, typed response.
- The TypeScript client must preserve existing callers while exposing the new metadata.

### Task 1: Durable mobile event gap metadata

**Files:**
- Modify: `apps/eeee/app/mobile/bridge.py`
- Test: `apps/eeee/tests/mobile/test_bridge.py` or the existing bridge test file

- [x] Write a failing test for an evicted cursor returning `hasGap=True` and `oldestCursor`.
- [x] Run the focused test and confirm it fails because the metadata is absent.
- [x] Implement the oldest-cursor comparison in `MobileBridge.events_after()`.
- [x] Add tests for fresh cursor zero and an empty table.
- [x] Run the focused bridge suite.
- [x] Commit the Python and TypeScript contracts together as one API-compatible change.

### Task 2: Typed mobile client contract

**Files:**
- Modify: `apps/mobile/src/client.ts`
- Test: `apps/mobile/tests/client.test.ts`

- [x] Add `hasGap` and `oldestCursor` to `MobileEventBatch`.
- [x] Assert a client can consume the metadata without changing event handling.
- [x] Run the TypeScript test and typecheck.
- [x] Commit the client contract together with Task 1 as one API-compatible change.

### Task 3: Integration verification

- [x] Run the full EEEE pytest suite: `1088 passed, 1 skipped`.
- [x] Run the mobile test and TypeScript typecheck.
- [x] Run encoding and diff checks.
- [ ] Open a Korean PR, wait for both CI checks, review the diff, merge only after success, and confirm no open PR remains.
