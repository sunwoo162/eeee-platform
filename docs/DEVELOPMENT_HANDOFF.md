# Gleave — durable development handoff

Updated: 2026-10-28 (Asia/Seoul). **The live Git working tree is authoritative; run `scripts/gleave-context.ps1` before any edit.** This file is a checkpoint, not a claim that every planned feature is complete.

## Reopen this project in a new chat

Use the local repo `C:\Users\user\Documents\gleave-unified-chat`. Tell the next assistant: “Continue Gleave, not standalone ISEOL. Read `AGENTS.md`, `docs/DEVELOPMENT_HANDOFF.md`, `docs/architecture/unified-chat-v1.ko.md`, and the newest direction reviews. Run `scripts/gleave-context.ps1` to inspect live Git state. Preserve all uncommitted work and do not touch main. Implement the next smallest verified task and update this handoff.” If the original chat is archived or unavailable, **the repository + commits + tests**, not a recalled conversation, is the development source of truth.

## Repository and ownership

- Active integration checkout / branch at this checkpoint: `gleave-unified-chat` / `feat/unified-chat`. Do **not** treat the separate worktree `C:\Users\user\Documents\eeee-platform` (`main`) as the active checkout.
- Remote tracking branch: `origin/feat/unified-chat`. The latest observed pre-milestone HEAD was `73658ce` on 2026-10-28 10:18 KST; never rely on this cached hash instead of live Git output.
- `main` integration/pull request is intentionally **not** part of the current feature work. No rebases, `reset --hard`, `git clean`, forced updates, or destructive cleanup.
- Key project specification: `docs/architecture/unified-chat-v1.ko.md`; product overview: `README.md`; architecture checkpoints: `docs/architecture/direction-review-01.ko.md` through `direction-review-10.ko.md`.

## Product goal and constraints

A **single local-first Windows application** with a chat-first interface, project-scoped cross-chat approved memory, GPT/Claude/local chat models, scoped Codex coding agent, past conversation import/review, optional learning, verifiable development outcomes, and extensible EEEE/ISEOL/ClaimLatch internals. A model switch must not reset canonical chat, project ID, ownership, or provenance. Importing a transcript must never silently approve memory or authorize training. Use explicit approval for external writes, code modifications, deployment, and billable provider calls.

## Verified implementation baseline (before this handoff milestone)

- Chat/project links, chat-first React UI and canonical message storage; GPT/Claude/manual provider selection code and rule-based Auto v0, **not** a benchmark-driven smart router.
- Codex task panel with owner-scoped workspace, readOnly vs workspaceWrite approval, durable task journal/restart handling. Authenticated real-model end-to-end code execution is still an open verification gate.
- ChatGPT/Claude/Codex export import with bounded JSON/JSONL/ZIP staging, provenance, deduplication, explicit review and selected-memory approval.
- AI-assisted optional memory proposal classification (new/duplicate/conflict/uncertain) with user consent, saved analysis, stale-context guards. Memory revisions and source history through `direction-review-10`.
- Immediately prior to this checkpoint, memory conflict replacement UI/API and opt-in provider benchmark runner were uncommitted. Consult current `git status`, commit history, and tests to know whether they have now been completed.

## Verification commands

From repo root, check the current branch and changes with `pwsh -NoProfile -File .\scripts\gleave-context.ps1`.

From `apps/eeee`, using the activated Python 3.12 environment with project dependencies:

```
python -m pytest -q tests/api/test_memory_ai_review.py tests/api/test_memory_benchmark_runner.py --disable-warnings --maxfail=1
python -m ruff check app/conversation_imports tests/api/test_memory_ai_review.py tests/api/test_memory_benchmark_runner.py
```

From `apps/desktop/chat-ui`: `npm run build`.

For wider acceptance, inspect `scripts/verify-core-product.ps1` and `scripts/verify-all.ps1`; do not claim those checks passed without running them at the new HEAD. Python tests with fake providers and a React build **do not** establish actual paid GPT/Claude response quality or a packaged Windows exe working.

## Next work after current memory features

1. Confirm all memory conflict replacement boundary cases: precise source/target, stale version, changed context, privacy, idempotency and safe UI approval. Keep edit/history atomic and do not auto-rewrite facts.
2. Benchmark GPT/Claude memory-review quality only on synthetic data, initially with a no-network dry-run and fake-provider tests. **Actual paid API evaluation needs separate explicit user approval and a bounded execution.**
3. Address memory retention/full-delete and restoration policy, version history UX, actual Windows packaged UI smoke/E2E, authenticated Codex and user-owned model checks.
4. Later: validated cost/quality Auto Router, richer agent diff/terminal/preview, local-model eval/opt-in learning and real authenticated team sharing. Treat all as incomplete until separately proven.

## How to update this file

At the end of every verified development milestone, record **date, branch/commit, exact files or feature, tests actually run, known failures/risks, and the immediate next task**. Prefer adding a dated entry below. If a chat ends suddenly, the next assistant must use Git and the last entry to resume rather than guessing.

## Milestone journal

- **2026-10-28 — recovery checkpoint:** Original chat was archived and unavailable. Recovered this repo by connected local Git inspection: `feat/unified-chat`, existing remote-tracked commits beyond locally cached `origin/main`, and memory-review work in the working tree. Explicit instruction: finish safely, commit tested feature work only, preserve main and the other linked worktrees.

- **2026-10-28 — conflict replacement and memory benchmark milestone:** In `feat/unified-chat`, the existing concurrent task produced `d8f7832` (atomic memory replacement and revisions), `c2f9e56` (confirmation UI), `4e2aa80` (opt-in GPT/Claude evaluation CLI), and `ff5bd50` (tests, CI and docs). These commits were observed live in Git, not inferred from chat. A further small benchmark parser hardening prevents non-object JSON from crashing and treats unsupported conflicts as uncertain. Before final integration, 20 memory/benchmark targeted tests passed, Ruff passed after the parser-type correction, and the React production build passed. No paid provider benchmark or actual Windows UI E2E was run.
- **2026-10-28 — continuity mechanism:** Added root `AGENTS.md` and read-only `scripts/gleave-context.ps1` to reconstruct branch/HEAD/uncommitted files/worktrees/last commits without relying on a ChatGPT conversation. Verified the script runs in Windows PowerShell 7 and makes no network calls or Git mutations. Do not interpret an active local tool process in an archived conversation as a guarantee of a future background service; check for concurrent Git activity before every edit.

- **2026-10-28 — verified checkpoint:** Wider import/memory/workspace/chat-scope regression suite: `51 passed, 1 warning in 70.43s`; focused memory benchmark suite: `20 passed`; Python Ruff: `All checks passed`; React/TypeScript production build succeeded. Offline benchmark dry-run reported `networkCalls: 0` and four planned synthetic cases. Additional model-payload validation fix committed as `d6100cf`. Actual provider live tests, billable benchmark, packaged Windows E2E, and full repository acceptance suites **not run in this checkpoint**. The Git branch, remote and files should be checked again with the handoff script on the next chat.
