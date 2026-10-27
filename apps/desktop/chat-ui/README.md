# Gleave Chat UI (P1)

Chat-first React/Vite frontend for the existing EEEE FastAPI conversation API.
This is a browser-served development build, not yet a packaged standalone Windows app.

## Local setup

In the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\eeee[dev]"
npm ci --prefix .\apps\desktop\chat-ui
npm run build --prefix .\apps\desktop\chat-ui
powershell -ExecutionPolicy Bypass -File .\scripts\chat-up.ps1
```

Open http://127.0.0.1:8000/chat/ while the API runs. The frontend is built
into `apps/desktop/chat-ui/dist`; the existing EEEE root route is unchanged.

For UI hot-reload, run `npm run dev --prefix apps/desktop/chat-ui` in a second
terminal. Vite proxies `/v1` to the FastAPI server and serves at /chat/.

## Implemented in P1

- Sidebar: personal/team folder groups, projects, sibling conversations, unassigned chats
- Create workspace/project/chat and move chats by dragging them over project folders
- Persistent conversation transcript, SSE updates, server-side request cancellation
- Read, add, and revoke approved project memory from the side panel
- Same-origin /v1 API; no third-party keys exposed to frontend
- Model selector: Auto, GPT, Claude, Personal LLM and Ollama; unavailable providers are shown but disabled.
- A manually selected model is stored on each turn. Auto uses an initial deterministic rule,
  not a measured cost-optimizing router.

## Connecting GPT and Claude

Configure server-side environment variables (not in browser code or Git):
```powershell
$env:OPENAI_API_KEY = "<your OpenAI API key>"
$env:ANTHROPIC_API_KEY = "<your Anthropic API key>"
# Optional API model overrides:
$env:GLEAVE_OPENAI_MODEL = "gpt-6.1-sol"
$env:GLEAVE_CLAUDE_MODEL = "claude-sonnet-5-5"
```
These are separately billed API connections, not a reuse of consumer chat subscriptions.
No network inference is made until a conversation turn is submitted.

## Codex agent panel (P3 foundation)

Use the code icon in a project chat's top bar. Gleave launches the installed
`codex app-server` via local stdio, not via a web scraping bridge.

1. Install and sign in to Codex CLI using its supported authentication flow.
2. Open a project chat and the Codex panel.
3. Click **Create dedicated workspace folder** for an empty managed folder,
   or enter an existing directory **relative to EEEE_WORKSPACE_ROOT**.
4. Start in `readOnly` to analyze a codebase without file edits.
5. For edits, select `workspaceWrite` and explicitly acknowledge that the
   agent can modify files inside that folder. Additional Codex approval
   requests show explicit accept/decline controls.
6. The app shows the answer, unified diff notifications, and task status.
   Cancel terminates the subprocess.

**Security constraints:** Codex tasks are loopback-only, folder bindings are
resolved and checked under the configured workspace root, unknown Codex
approval requests fail closed, and tasks have bounded time/concurrency.
An owner may create a managed folder, but it starts empty; no external
repository has been imported automatically. If you allow write mode, changes
may be made before a final diff appears. Review backups and Git status first.
Codex may send project data to its service. Do not store credentials in workspaces.

**Limitations:** This is a first development-tool panel, not yet a seamless
Codex turn inside the canonical Gleave chat; the Codex option in the general
model selector stays disabled until that integration is complete. Task event
history is currently in memory and does not survive server restarts. A
protocol-only CLI initialization smoke test passed locally; real authenticated
Codex model runs still require user setup and end-to-end testing.

## Not implemented yet

Seamless Codex turns in regular chat, persistent agent task logs, empirical
cost-based smart routing, conversation imports, cloud team authentication,
full file/terminal/browser agent panels, Windows standalone packaging.
The local team folder schema is *not* an authenticated multi-user sharing feature.
