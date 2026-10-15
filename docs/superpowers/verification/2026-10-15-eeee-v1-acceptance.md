# EEEE v1 Acceptance Record

Date: 2026-10-15
Branch: `codex/eeee-main-sync`
Head at verification start: `08d99f0`
Final verification head: `7f2182a`

This record separates deterministic checks from environment-dependent checks.
It does not claim that the local Ollama model, packaged Windows executable, or
external plugin connector authentication were verified in this environment.

## Acceptance matrix

| Area | Result | Evidence / boundary |
| --- | --- | --- |
| Core paths and single-process lock | PASS | `tests/core/test_paths.py`, `tests/core/test_lock.py` |
| Durable conversations and migrations | PASS | `tests/conversations/test_store.py`, `tests/storage/test_conversation_migrations.py`; request idempotency is guarded by a unique SQLite index |
| One conversation API and idempotent turns | PASS | `tests/api/test_conversation_routes.py`, `tests/api/test_request_flow.py`, duplicate request regression test |
| SSE events, cancel, retry, and failure persistence | PASS | `tests/api/test_request_flow.py`, `tests/conversations/test_service.py` |
| Restart recovery | PASS | `scripts/smoke_restart_recovery.py`; recovered requests become `interrupted` with `core_restarted` |
| Desktop thin-client flow | PASS (automated) | `tests/desktop/test_conversation_client.py`, `test_conversation_session.py`, `test_conversation_worker.py`, `test_chat_window.py` |
| Bubble UX contracts | PASS (automated) | Dynamic text measurement, no fixed 24 px body, terminal answer click starts fresh input, timer only hides terminal bubble, draft survives error |
| Capability lifecycle and permission boundary | PASS | `tests/capabilities/test_manager.py`, `test_capability_manifest.py` |
| Lazy optional runtime imports | PASS | `tests/agent/test_lazy_runtime.py`, `tests/packaging/test_package_boundaries.py` |
| Explicit memory boundary | PASS | `tests/api/test_memory_api.py`, `tests/memory/test_conversation_boundary.py`, `tests/memory/test_memory_store.py` |
| Selectable conversation provider | PASS (deterministic) | `tests/conversations/test_providers.py`, `tests/core/test_paths.py`, `tests/api/test_conversation_routes.py` |
| Empty provider response quality gate | PASS | `tests/conversations/test_service.py` rejects blank assistant output as `provider_empty_response` |
| Growth feedback ledger and explicit promotion | PASS | `tests/memory/test_growth_feedback.py`, `tests/api/test_memory_api.py`; ordinary feedback stays out of active memory |
| Bounded approved-memory context | PASS | `tests/conversations/test_context.py`, `tests/memory/test_conversation_boundary.py` |
| Warm Core health benchmark | PASS | 10 warm `/health` requests, average `0.7426 ms` in this run |
| Full deterministic suite | PASS | `870 passed, 1 skipped, 1 warning` in `135.05s` |
| Web GPT active-brain policy | PASS | Default EEEE route uses Web GPT; missing Web GPT never silently falls back to Ollama |
| Local Ollama live generation | BLOCKED | `scripts/smoke_ollama.py` runs successfully and reports `model_missing` with exit code `2`; no local model is configured |
| Packaged Windows EXE | NOT RUN | PyInstaller is not installed in this environment; static package-boundary checks pass |
| Live ChatGPT Web bridge | PASS | Dedicated browser bridge reported `ready`; direct `/chat` completed; EEEE API round trip emitted `request.accepted`, `message.started`, `message.delta`, and `message.completed`, then persisted user + assistant messages |
| External plugin connector auth | NOT RUN | Plugin-specific OAuth/login sessions still require separate user-authorized verification |

## Commands run

```powershell
Set-Location C:\Users\user\Documents\eeee-core-redesign\apps\eeee
$env:PYTHONPATH='.'
python -m pytest tests -q
python -m pytest tests/api/test_conversation_routes.py tests/api/test_request_flow.py tests/api/test_memory_api.py tests/core/test_lifecycle.py tests/core/test_recovery.py tests/desktop/test_conversation_client.py tests/desktop/test_conversation_session.py tests/desktop/test_conversation_presentation.py tests/desktop/test_chat_window.py tests/capabilities/test_manager.py tests/memory/test_conversation_boundary.py tests/memory/test_memory_store.py tests/packaging/test_package_boundaries.py tests/smoke/test_scripts.py -q
python scripts/benchmark_core.py --iterations 10
python scripts/smoke_restart_recovery.py
python scripts/smoke_ollama.py
```

The previous acceptance record predates the growth/Web GPT changes. The final
full-suite result for this branch is `870 passed, 1 skipped, 1 warning` in
`135.05s`.

The Ollama command exits with code `2` when no model is configured. That is a
truthful blocked result, not a test failure hidden as success.

## Remaining acceptance work

1. Install/configure the intended Ollama model and verify real streaming,
   timeout, cancel, retry, and Korean response quality.
2. Build the Windows package with PyInstaller and run the packaged
   `--self-test` plus a real idle/restart cycle.
3. Verify each external plugin connector's OAuth/login flow in a live user
   session. The ChatGPT Web bridge itself is verified below.

Those are environment-gated checks; the Core implementation does not mark
them as complete until their evidence exists.

## Fresh growth/Web GPT verification

```powershell
Set-Location C:\Users\user\Documents\eeee-core-redesign\apps\eeee
python -m pytest tests -q
python -m pytest tests/smoke/test_scripts.py -q
python scripts/smoke_ollama.py  # expected exit code 2 when no model is configured
```

Result: `870 passed, 1 skipped, 1 warning in 135.05s (0:02:15)`.

The remaining warning is the installed Starlette/httpx compatibility warning.
No live Ollama model was claimed from this deterministic run. The separate
live Web GPT check completed successfully after the user authenticated the
dedicated browser profile:

- bridge health: `connected=true`, `browserStatus=ready`;
- bridge smoke response: `status=completed` with a conversation reference;
- EEEE round trip: runtime provider `chatgpt_web`, terminal events through
  `message.completed`, and two persisted messages;
- response encoding check: stored Korean response `연결 확인됐어요!` preserved
  as UTF-8.
