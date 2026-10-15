# Gleave Desktop

The Desktop target is the local execution host for Gleave. It packages the EEEE
API, SQLite state, ClaimLatch adapter, ISEOL project runtime, and the desktop
widget from `apps/eeee/app/desktop`.

Desktop owns the source of truth and the local AI/tool permissions. It exposes
the paired Mobile bridge; it does not upload the EEEE database or require a
hosted login.

The aggregate repository keeps the implementation under `apps/eeee` so the
kernel and desktop distribution can be tested together. This directory is the
deployment boundary for a future standalone `gleave-desktop` repository.

The embedded runtime is started from `apps/eeee/app/desktop`. Desktop owns the
SQLite database, EEEE Core lifecycle, optional project capabilities, ClaimLatch
adapter, and Mobile bridge. The widget is a thin client: it starts with Core's
conversation API and loads optional runtimes only when their capability is
actually used. The development shell can be launched with
`scripts/desktop-up.ps1` or `gleave-desktop`; it starts the API on loopback and
opens the EEEE widget in one process.

The widget's EEEE chat opens or resumes a conversation through
`/v1/conversations`, submits turns through
`POST /v1/conversations/{conversation_id}/turns`, and consumes the streamed
events from `/v1/requests/{request_id}/events`. This keeps messages, retries,
drafts, cancellation, and restart recovery in Core's durable state. The
project control center retains `POST /api/assistant/route` as a compatibility
route for project operations; it is not the chat transport. The desktop state
endpoint still exposes selected Project Runtime, ClaimLatch
(`claimlatch-v0.2.0`) health, redacted lifecycle events, and connector state.
`POST /api/desktop/pairing/code` is the only Desktop action needed to begin
Mobile pairing. It returns a short-lived six-digit code, never an access token;
Mobile remains a remote client of Desktop.

To produce a Windows executable locally, install PyInstaller in the build
environment and run:

```powershell
python -m pip install -e ".\\apps\\eeee[desktop,desktop-build]"
.\scripts\build-desktop.ps1
```

The output is `build\desktop\GleaveDesktop.exe`. The executable still uses the
user's local `.gleave` data directory and provider configuration; packaging does
not add a hosted service or move secrets into the binary.

The packaged runtime can be smoke-tested without opening a window:

```powershell
build\desktop\GleaveDesktop.exe --self-test
```

Exit code `0` confirms that the embedded loopback API started and its health
endpoint returned `ok`.
