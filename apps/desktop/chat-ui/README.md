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

## Not implemented yet

Codex app-server execution and model selection, empirical cost-based smart routing,
conversation imports, cloud
team authentication, file/terminal/browser agent panels, packaging. Do not
describe them as supported until tested. The local team folder schema is *not*
an authenticated multi-user sharing feature.
