# EEEE v1 Acceptance Record

Date: 2026-10-15
Branch: `codex/eeee-main-sync`
Head at verification start: `08d99f0`
Final verification head: `d39ce9e`

This record separates deterministic checks from environment-dependent checks.
It does not claim that external plugin connector authentication was verified in
this environment. Local Ollama generation, the packaged Windows executable,
and the live Web GPT bridge have separate evidence below.

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
| Local Ollama live generation | PASS (explicit legacy lane) | Explicit `qwen3:4b` status was `ready`; real stream returned 12 chunks and a Korean response. Default EEEE provider remains Web GPT; default `qwen2.5:7b` smoke remains `model_missing` and is not auto-selected |
| Packaged Windows EXE | PASS | `scripts/build-desktop.ps1` produced `build/desktop/GleaveDesktop.exe`; packaged `--self-test` and `--gui-self-test` both exited `0`; a two-run restart cycle exited `0 → 0`; no secret-like files were bundled |
| Live ChatGPT Web bridge | PASS | Dedicated browser bridge reported `ready`; direct `/chat` completed; EEEE API round trip emitted `request.accepted`, `message.started`, `message.delta`, and `message.completed`, then persisted user + assistant messages |
| External plugin connector auth | NOT RUN | Plugin-specific OAuth/login sessions still require separate user-authorized verification |

## Review hardening completed

- Web GPT remains the selected provider while the bridge is unavailable; the
  same live runtime object is retained so a user login can be followed by a
  retry without restarting EEEE. `/v1/runtime` refreshes the bridge status.
- An `auth-required` hidden bridge is no longer reused as a healthy startup
  session, so the explicit login path can open the visible persisted profile.
- Connector health transport failures fail closed as `provider_unavailable`;
  capabilities stay hidden and OAuth callbacks report connection failure rather
  than incorrectly showing success.
- The desktop build script rebuilds the embedded ISEOL bridge and documents the
  clean-checkout `npm ci` prerequisite. The Ollama README now uses the actual
  `EEEE_OLLAMA_MODEL` setting.

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

1. Verify timeout, cancel, retry, and Korean response quality for the
   explicitly selected legacy Ollama lane if it is retained for debugging.
2. Optional visual idle observation remains manual; the automated packaged
   restart cycle and GUI import self-test are complete.
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

The explicit legacy Ollama check also completed separately with
`qwen3:4b`: status `ready`, 12 streamed chunks, and a Korean response. The
default smoke command still reports `model_missing` because its configured
legacy model is `qwen2.5:7b`; this does not affect the Web GPT primary route.

## Release stabilization verification — 2026-10-19

The existing EEEE/ISEOL implementation and the release-review fixes were
re-verified before release cleanup. Fresh results:

- Focused EEEE assistant/API/desktop/ISEOL/memory/plugin/project-runtime
  coverage: `416 passed, 1 warning`.
- Full EEEE Python suite: `956 passed, 1 skipped, 1 warning`.
- Plugin/capability/OAuth/intent lifecycle suite: `87 passed, 1 warning`.
- `scripts/verify-all.ps1 -Full`: EEEE `956 passed, 1 skipped, 1 warning`,
  ISEOL `25/25`, ClaimLatch adapter `5/5`, Mobile `1/1`; unified verification
  passed.
- `scripts/verify-core-product.ps1`: `375 passed, 1 warning`; static UI
  checks `2/2`; strict UTF-8 and `git diff --check` passed.
- `scripts/build-desktop.ps1` completed successfully. The packaged
  `GleaveDesktop.exe --self-test` and `--gui-self-test` both returned exit
  code `0` when launched through a process handle.

Repository hygiene was also corrected: an ignored, local-only
`apps/eeee/.env` is now allowed to remain outside Git while tracked or
non-ignored secret-like files continue to fail the repository check. The
local Gmail OAuth values were not copied into the repository or package.

External connector account authentication remains an environment-gated
manual check. This record does not claim that every provider's OAuth session
or external side effect has been newly verified by the deterministic suite.

Release-review fixes included in this verification:

- External plugin approval now requires a server-issued approval execution ID
  and a matching request fingerprint; forged `approved=true` requests and
  changed-request replays remain awaiting approval.
- Plugin connector output and provider failures are redacted or converted to
  stable error codes before returning or persisting them.
- OAuth start failures now map permission errors to 403 and connector/config
  failures to actionable 409/503 responses.
- ISEOL compiles intent-selected agents, skips irrelevant backend/data work,
  and always retains test, security, review, documentation, and integration
  gates.
- Missing required extensions and failed QA/ClaimLatch/release evidence now
  propagate `blocked` into the durable project outcome instead of being
  persisted as completed.
- The meal planner scaffold renders user meal values with DOM text nodes,
  preventing user-controlled `innerHTML` interpolation.

The packaged desktop verification was also repeated with the actual CLI
flags: `--self-test`, `--gui-self-test`, and a second `--self-test`; all three
returned exit code `0`.

## Post-live completion verification

```powershell
.\scripts\build-desktop.ps1
.\scripts\verify-all.ps1 -Full
Set-Location apps\eeee
$env:PYTHONPATH='.'
python -m pytest tests/plugins tests/capabilities tests/api/test_plugin_control_center.py tests/api/test_plugin_oauth_routes.py -q
```

Results:

- Packaged Desktop: `GleaveDesktop.exe` built; `--self-test` and
  `--gui-self-test` passed.
- Unified verification: `870 passed, 1 skipped, 1 warning`; ISEOL 25 tests,
  ClaimLatch adapter 5 tests, and Mobile 1 test passed.
- Plugin lifecycle contracts: `65 passed, 1 warning`.
- Generated package contained no `.env`, key, certificate, or secret-like
  files.
- Desktop persistence: `C:\Users\user\AppData\Local\Gleave\config.json`
  stores Web GPT enabled/autostart settings and the dedicated profile path;
  `connect_desktop_api()` loaded that profile and returned Core health `ok`.
