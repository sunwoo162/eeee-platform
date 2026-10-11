# 2026-10-08 EEEE Assistant Redesign Baseline

## Scope

Baseline captured before implementing the EEEE Desktop Assistant product design.
Existing dirty worktree changes were preserved.

## Results

### Unified verification script

Command:

```powershell
.\scripts\verify-all.ps1 -PythonPath C:\Users\user\Documents\eeee-platform-env\Scripts\python.exe
```

Result: **blocked**

- EEEE: 116 passed, 3 failed
- ISEOL and ClaimLatch stages were not reached because the script stops on EEEE failure

The three failures are existing end-to-end tests that expect synchronous project completion:

- `tests/e2e/test_assistant_project_runtime.py::test_project_request_survives_app_restart_with_truthful_connector_states`
- `tests/e2e/test_todo_generation.py::test_user_can_request_todo_and_receive_a_generated_project`
- `tests/e2e/test_todo_generation.py::test_user_can_request_a_login_web_todo_and_receive_a_full_stack_project`

Observed failure: the current route runs the specialist graph inline, returns the blocked
handoff response, and therefore does not expose the expected planning session or project
profile. This confirms the architecture gap: project execution is still coupled to the
synchronous request instead of returning an accepted background execution.

### ISEOL build

```powershell
Push-Location packages\iseol
npm.cmd run build
Pop-Location
```

Result: **passed** (`tsc -p tsconfig.json`).

### ISEOL quality/release tests

Result: **25 passed**.

### ClaimLatch adapter tests

Result: **5 passed**.

## Decisions from the baseline

1. Do not weaken the truthful BLOCKED behavior to satisfy the three old synchronous tests.
2. Implement the accepted-background-execution contract first.
3. Update those tests to assert accepted execution, durable project identity, and eventual
   completion/blocking from the execution store.
4. Do not claim the product is complete until the real Todo live E2E passes through the new
   asynchronous path.

