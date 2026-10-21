# Conversation List Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow Desktop and Mobile history clients to page through canonical conversation summaries without loading an unbounded or repeatedly duplicated list.

**Architecture:** Preserve the existing array response and default behavior. Add an optional keyset cursor composed of `beforeUpdatedAt` and `beforeConversationId`; the canonical store filters by `(updated_at, id)` in the same order used for the list. This avoids offset drift when new conversations arrive while a user is paging.

**Tech Stack:** Python, SQLite, FastAPI-compatible query parameters, TypeScript client, pytest, node:test.

## Global Constraints

- Existing callers that only send `query` and `limit` keep receiving the same array shape.
- The canonical Desktop conversation store remains the source of truth for Mobile history.
- Cursor values are explicit and stable; no in-memory pagination state is introduced.
- No plugin implementation is added in this task.

## Tasks

### Task 1: Canonical store keyset pagination

- [x] Write a failing test for multiple pages, including equal timestamps and search filtering.
- [x] Implement optional `(updated_at, id)` cursor filtering in `list_transcript_summaries()`.
- [x] Validate malformed cursor combinations at the API boundary.
- [x] Run focused store/API tests.

### Task 2: Desktop/Mobile route and client contracts

- [x] Add cursor query parameters to Desktop and Mobile history-list routes.
- [x] Add typed optional cursor arguments to the TypeScript client.
- [x] Add route/client regression tests while preserving the array response.

### Task 3: Verification and integration

- [x] Run the full EEEE pytest suite: `1089 passed, 1 skipped`.
- [x] Run Mobile tests and TypeScript typecheck.
- [x] Run encoding and diff checks.
- [ ] Open a Korean PR, wait for CI, review, merge, and verify the branch is clean.
