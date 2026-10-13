# Assistant UI and Conversation Hardening Plan

> **Execution note:** Follow the test-driven workflow for every task: write a focused failing test, run it to confirm the failure, implement the smallest safe change, then run the focused and regression suites.

## Goal

Make the desktop assistant reliable during normal use: speech bubbles must remain usable on small or crowded screens, local replies must receive the right conversation context, and submit/reply state must not duplicate or get stuck. Keep the existing pet visuals and provider split intact.

## Task 1: Make speech-bubble geometry screen-safe

**Files:** `apps/eeee/app/desktop/window.py`, `apps/eeee/tests/desktop/test_window.py`

- Add a regression test for a surface taller than the available screen and for the right/bottom screen edges.
- Fix positioning so an oversized surface is anchored to the visible screen instead of producing a negative clamp range or leaving the bubble off-screen.
- Preserve the current tail alignment and dynamic wrapped-height behavior; do not reintroduce a fixed global height cap.
- Verify with focused desktop tests and a small-geometry Qt smoke check.

## Task 2: Strengthen local conversation context and response quality

**Files:** `apps/eeee/app/agent/local_runtime.py`, `apps/eeee/app/assistant/secretary.py`, `apps/eeee/tests/agent/test_local_runtime.py`, `apps/eeee/tests/assistant/test_assistant_service.py`

- Add a failing test proving that a normal follow-up receives recent turns and preference/memory context without exposing internal routing instructions.
- Ensure the local fast path keeps the current conversation context bounded and deterministic, while avoiding canned/fixed responses for ordinary requests.
- Preserve provider identity behavior and prompt-leakage protection.
- Verify focused local-runtime, secretary, and assistant-service suites.

## Task 3: Stabilize submit/reply lifecycle

**Files:** `apps/eeee/app/desktop/window.py`, `apps/eeee/tests/desktop/test_window.py`

- Add failing tests for duplicate submit prevention while busy, clearing input only after an accepted submit, and visible error recovery.
- Make busy/complete/failure transitions explicit and ensure the reply bubble timer is restarted only for the current reply.
- Keep Enter and the visible input surface on the same route and avoid duplicate background requests.
- Verify focused desktop tests and the assistant API contract tests.

## Task 4: Product verification and delivery

**Files:** tests/build output only; no unrelated files staged

- Run focused suites, then the full test suite.
- Build the desktop executable and launch the newest build once for a smoke check.
- Review the diff for encoding, asset, and unrelated-worktree safety.
- Commit in coherent units, push the feature branch, open a PR using `.github/pull_request_template.md`, obtain review evidence, squash-merge, refresh `main`, and delete the merged branch.

## Acceptance criteria

- No oversized bubble is positioned with a negative clamp range or rendered wholly outside the available screen.
- Ordinary follow-ups use recent conversation context and relevant preferences/memory, while internal prompt text never appears in replies.
- Repeated Enter/click events while a request is running create one request, and failure returns the UI to an actionable state.
- Focused tests, full suite, build, and launch smoke check pass.
