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
   Cancel terminates the subprocess. When an agent job finishes, Gleave saves
   the original user task and its final Codex result to the same project's
   canonical chat transcript. The panel can reload that chat directly.

**Security constraints:** Codex tasks are loopback-only, folder bindings are
resolved and checked under the configured workspace root, unknown Codex
approval requests fail closed, and tasks have bounded time/concurrency.
An owner may create a managed folder, but it starts empty; no external
repository has been imported automatically. If you allow write mode, changes
may be made before a final diff appears. Review backups and Git status first.
Codex may send project data to its service. Do not store credentials in workspaces.

**Limitations:** Read-only Codex jobs can be launched directly from the chat
model selector, but file edits still require explicit permission in the drawer.
Task state and approval decisions survive restarts; the agent process itself
cannot automatically resume after a restart. Protocol-only CLI initialization
passed locally; live authenticated model runs still require user setup and
end-to-end testing.

## Not implemented yet

Fully unified token streaming and resumable Codex sessions, empirical
cost-based smart routing, conversation imports, cloud team authentication,
full file/terminal/browser agent panels, Windows standalone packaging.
The local team folder schema is *not* an authenticated multi-user sharing feature.

## Codex in the main chat (P3 follow-up)

On machines with a detected Codex CLI, **Codex** appears in the normal model
selector. It runs *readOnly* through the same approved project-folder task
pipeline and opens the development drawer for progress and approval handling.
For code edits, use `workspaceWrite` from the development drawer after explicit
consent; the model selector alone never grants file-write permission.

The finalized task and Codex output appear in the same canonical conversation
as GPT/Claude messages. The task journal (schema v9) also stores project-scoped
task status, events, approval decisions and snapshots. After restart, active
jobs are marked interrupted, not silently resumed or approved. Chat owners can
query per-task audit and their conversation's Codex task history.

## Import past AI conversations (P4 MVP)

Use the upload icon in the chat titlebar, choose a service and select a
conversation export **JSON** (ChatGPT or Claude) or **JSONL** (Codex CLI).
The browser previews text-only conversations without storing them. Select
which conversations to save (up to 20 in one action) and assign them to a
personal/team project folder or the unassigned conversation list. Repeated
imports with the same provider/source ID are skipped. Original chat titles and
text roles are preserved; tool/system/developer and image records are excluded.

**Privacy boundary:** Importing a transcript never trains the personal model
and never auto-creates approved project memories. Imported user messages are
also excluded from sibling-chat automatic project context. Open an imported
chat and explicitly select "Approve this message as project memory" to create
a traceable approved note. Continuing an imported chat with a cloud model
may send the chosen conversation to that model; importing alone is local.

**Current limits:** max 8 MB input, 200 readable conversations per file, 20
selected per import action, up to 500 imported text messages per conversation.
Extract conversations.json from official export ZIP archives before selecting
it. Formats change; unsupported branches, attachments, images and tool output
are deliberately omitted. Large exports need manual splitting in this MVP.
