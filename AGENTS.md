# Gleave — instructions for a new AI development session

This repository is **Gleave**, a local-first unified AI chat and developer workspace. EEEE, ISEOL, and ClaimLatch are internal components, **not** separate projects to substitute for Gleave. Do not conflate this repository with the standalone ISEOL repository.

## Always begin with evidence

1. Read `docs/DEVELOPMENT_HANDOFF.md`, `docs/architecture/unified-chat-v1.ko.md`, and the latest `docs/architecture/direction-review-*.ko.md`.
2. Run `pwsh -NoProfile -File scripts/gleave-context.ps1` from this checkout (or equivalent read-only Git commands if PowerShell 7 is unavailable). Treat the live Git output as more recent than this document.
3. Identify the current branch, HEAD, uncommitted changes, all linked worktrees, test environment, and any existing work before editing.
4. Preserve all existing changes. Never reset, clean, delete worktrees, force-push, or merge to `main` without an explicit user instruction. Do not stage unrelated files. If another chat/agent is already editing this checkout, do not overwrite its in-flight files or commit its changes; inspect current commits and coordinate distinct tasks.
5. Separate **implemented**, **tested with fakes**, **actually integrated with a provider**, and **deployed/validated in Windows**. Tests or AI descriptions alone do not prove real-world success.

## Product invariants

- One chat-first UI, optionally revealing Codex/file/diff/test panels for development tasks.
- One canonical conversation history independent of GPT, Claude, Codex, or local model selection; preserve source/provider/task provenance.
- Strict personal/workspace/project boundaries, explicit project memories, and reviewed imports; imports never auto-promote to memory or model training.
- Codex is a separately authorized agent. Read-only analysis and workspace writes have different permissions. No silent model fallback, unauthorized file edits, API cost, external publishing, or deployments.
- EEEE owns assistant routing/memory, ISEOL manages project execution, ClaimLatch verifies evidence-backed claims and risky actions. Actual code/test evidence is necessary.
- Main branch and other worktrees remain untouched unless instructed. The feature branch is the integration target for normal incremental work.

## Development discipline

- Inspect existing interfaces before implementing, make narrowly scoped changes, add tests for security and failure paths, then run Python/React checks.
- Record architecture decisions and gaps in an appropriately numbered `docs/architecture/direction-review-*.ko.md`; never mark unverified capabilities finished.
- Commit only files belonging to the tested change, push only the explicitly intended feature branch, and refresh `docs/DEVELOPMENT_HANDOFF.md` at the end of each meaningful milestone.
- On a new chat, ask for access to the same local checkout if no remote filesystem tool is connected. Do not assume chat history itself can be recovered or the connected device is still online.
