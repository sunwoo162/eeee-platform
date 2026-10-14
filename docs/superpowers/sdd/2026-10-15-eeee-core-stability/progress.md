# EEEE core stability verification

Plan: `docs/superpowers/plans/2026-10-15-eeee-core-stability.md`

## Baseline and findings

- Correct test root is `apps/eeee`; `PYTHONPATH=.` is required.
- Baseline before this work: 790 passed, 1 skipped, 443 warnings.
- Reproduced the main regressions: the five-second timer cleared non-empty drafts and hid the surface during a slow request; status refresh could also replace a valid assistant response after a missing project profile.
- Existing linked worktree `C:\Users\user\Documents\eeee-platform-redesign` was used. The dirty `eeee-platform` checkout was left untouched.

## Implemented

- `ConversationState` now separates input, processing, typing, and finished-reply phases. Expiry is allowed only for an empty input or a completed reply.
- Bubble height and width are derived from measured text geometry with tail-safe padding; no one-line fixed-height assumption remains in the active rendering path.
- Reply-bubble click opens a fresh input state, and the desktop route carries the durable `desktop-default` conversation ID.
- Status refresh errors no longer discard a valid assistant route result.
- The desktop session remains compatible with older client adapters that do not yet accept a conversation ID.

## Verification

- Focused state/UI/session suite: 91 passed.
- Client/session/API/memory suite: 29 passed.
- Desktop GUI/runtime suite: 89 passed.
- Local-provider and memory suite: 25 passed.
- Full EEEE suite from `apps/eeee`: **800 passed, 1 skipped, 443 warnings**.
- `python -m app.desktop --self-test`: exit code 0.
- `python -m app.desktop --gui-self-test`: exit code 0.
- Packaged `build\\desktop\\GleaveDesktop.exe` built successfully; packaged `--self-test` and `--gui-self-test` both exited 0.

## Deferred by scope

- Plugin implementations and external connector development remain deferred. The core now provides the stable local conversation, memory, desktop lifecycle, and plugin-control boundary needed for that next phase.
- The existing FastAPI/Starlette deprecation warnings remain non-blocking follow-up maintenance items; they do not hide test failures.
