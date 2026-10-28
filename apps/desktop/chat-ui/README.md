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

**ZIP import (P4 extension):** Upload your ChatGPT/Claude official export
ZIP directly or select a text JSON/JSONL. The Gleave local Core accepts up to
64 MB per upload; ZIP entries are never extracted to disk. Each text
transcript is bounded to 48 MB after inflation. Entries with unsafe names,
oversized content or encryption are rejected. The server supports at most
1,000 readable conversations in the uploaded data, shows paginated previews,
and saves only up to 20 selected conversations at once. Original dedup IDs are
preserved. Each conversation is limited to 500 text messages, with 15,000
characters per message; longer records fail rather than being silently cut.

Previews are volatile and expire after 30 minutes or on restart; no original
archive is persistently stored. Parsed previews occupy memory temporarily,
with at most 3 per local user. For ZIP files, ChatGPT/Claude must have one
`conversations.json` entry. Codex ZIPs may contain multiple .jsonl sessions.

**Memory candidates (P4 extension):** The project's memory panel proposes
candidate decisions/preferences found in imported user-authored messages.
Candidate detection currently uses transparent *local keyword heuristics*, not
an AI model or fact verification. It excludes likely credentials and allows
the user to edit and then explicitly approve or dismiss each candidate.
Only approved text enters the shared project-memory context. Dismissals and
approvals are persisted with message provenance. Exported tool output and
assistant claims are never automatically elevated into memories.

**Limitations:** Older JSON-only API calls retain the original 8 MB limit.
The upload endpoint is local-only and has an in-process staging cache; this
is not resumable chunked transfer. Unsupported export formats, media and
embedded attachments remain excluded. A real-model memory extraction and
approval-quality evaluation pipeline have not yet been built.

## AI-assisted project-memory review (P4 extension)

Open the project memory panel after importing transcripts. Gleave first
lists user-authored project-decision candidates using **local heuristics**,
without sending anything to an AI service. To check a specific candidate for
potential duplication or contradiction, explicitly choose an available
GPT/Claude/local Ollama model and acknowledge that the candidate text plus
up to 12 approved project notes will be sent to the selected provider.
GPT/Claude can process this information in the cloud and incur separate API
charges; no model is called merely by viewing the memory panel.

The model returns a structured, unverified proposal with `new`,
`duplicate`, `conflict`, or `uncertain` verdict, a suggested rewrite,
reason and validated references to existing notes. Gleave saves the review
for the candidate, but **does not auto-save the suggestion as a memory**.
A human can revise it and explicitly approve or dismiss. Similarity judgments
may be incorrect. Warning verdicts require a separate acknowledgement at both
the frontend and backend before approval. The backend blocks exact normalized
duplicates, rejects obvious secret patterns and invalidates stale analyses
when previously approved notes change.

**Current limitations:** This is on-demand AI review, not a trained memory
extractor scanning all conversation history autonomously. Model/API connection
and billing must be configured by the user, and real-provider quality has not
been proven by unit tests. Imported assistant/tool messages are not promoted
to memories. Existing local user-header identity is not a production
multi-user authentication mechanism.

## Project-memory provenance and revision history

Open a project's memory panel and select **이력·수정** on an approved note.
The detail view lists the source conversation (only if you own that private
conversation), import provider and original exported conversation ID, as well
as all subsequent edit and revocation versions. Edit a note and save to replace
the active content. The Core checks `expectedVersion` to prevent stale
concurrent browser tabs from overwriting a newer edit. Deleting a note revokes
it from project context and writes another revision; neither operation silently
restores old content. Older notes migrated from previous schema versions
receive a single `legacy_snapshot`, not invented prior revision history.

For offline, reproducible **model comparison**, use the synthetic benchmark at
`docs/architecture/memory-review-benchmark.json` with results recorded
separately for each provider. Run from `apps/eeee`:

`python -m app.conversation_imports.evaluation --gold ../../docs/architecture/memory-review-benchmark.json --predictions predictions.json`

`predictions.json` must be an array of objects with `caseId`, `provider`,
`verdict`, and `relatedMemoryIds`. The evaluator performs **no model calls**
and scores nothing unless predictions are provided. Automated fixtures only
verify the scoring implementation, not actual GPT or Claude quality.

## Resolving conflicting project memories (P5)

When AI review flags a candidate as a possible **conflict** with an approved
project memory, expand the suggested comparison, acknowledge the risk and
choose **기존 기억을 새 결정으로 교체**. Gleave shows both versions and asks
for explicit final confirmation before performing any change.

The backend requires the original owner-visible import message, previously
recorded conflict analysis, a referenced active target memory, an unchanged
project-memory snapshot digest, an exact expected target version, no duplicate
active note, and an explicit acknowledgement. The existing memory ID is
preserved; the new source message and old/new contents are retained in its
revision history. One atomic transaction records replacement and marks the
candidate reviewed. This is never triggered by an AI answer alone.

## Opt-in GPT/Claude memory-review benchmark

Gleave also has an optional CLI evaluation runner using the same system
prompt as the product's memory reviewer. Its default command is a **dry run**,
without any API request:

python -m app.conversation_imports.evaluation_runner --gold ../../docs/architecture/memory-review-benchmark.json --provider gpt

From apps/eeee, the user must explicitly select a provider, an output file,
--execute and --confirm-api-charges before any real API request is made.
At most 8 synthetic cases are sent in one run. Never run this automatically
as part of CI. Predictions can be scored with evaluation.py. No real GPT or
Claude performance numbers or API costs are claimed until actual runs exist.
