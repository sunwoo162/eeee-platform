# Iseol Calendar and Code Review Design

## Goal
Extend Iseol with project calendar management, GitHub schedule synchronization, and a clean Gemini Code Assist-style pull request review bot without disrupting existing Notion, Figma, GitHub log, scrum, contest, voice, or music features.

## Scope
This design adds three connected subsystems:
1. Project-scoped Google Calendar integration and Discord schedule controls.
2. GitHub issue/milestone to calendar synchronization with explicit mapping state.
3. Automated AI pull request review that posts concise summaries and only high-value inline comments.

## Existing Architecture
The bot currently creates project categories and project channels, stores project metadata in `data/projects.json`, uses Octokit for GitHub integration, and runs polling/webhook-like background services from `src/index.ts`. Existing project creation already provisions Notion, Figma, and frontend/backend GitHub log channels.

## Architecture Decision
Keep the current centralized Iseol server model for this iteration. Use the existing GitHub token and Octokit integration instead of migrating immediately to a GitHub App. New GitHub-facing code must be isolated behind service interfaces so authentication can later be replaced by a GitHub App installation token without changing Discord command or review-domain logic.

Google Calendar will use OAuth2 credentials for one Iseol-owned Google account. Project calendars will be secondary calendars owned by that account. OAuth secrets and refresh tokens must remain environment/secret storage only and must never be written to `projects.json` or committed.

## Project Calendar UX
Each project created by `/project create` gets a new `📅・일정` text channel. The first pinned message is the schedule control panel.

The panel exposes compact actions for:
- 일정 추가
- 일정 보기
- 일정 수정
- 일정 삭제
- GitHub Issue 생성
- Google Calendar 열기

Discord interactions use modals/selects for fields rather than long slash commands. The schedule panel should stay visually compact and should not continuously post status noise.

Each project stores only identifiers and mapping metadata such as `calendarId`, `calendarChannelId`, and the pinned panel message id.

## Calendar Data Flow
Discord-created project events are created in Google Calendar first. Only after Calendar creation succeeds is the local mapping persisted. Update/delete operations follow the same remote-first rule to avoid local state claiming success when Google rejects the operation.

Calendar events created from GitHub work items include machine-readable private metadata linking project id, repository, issue or milestone number, and source type. This prevents title-based matching.

## GitHub Schedule Synchronization
GitHub milestones with due dates are synchronized into the project calendar. GitHub issues do not provide a native generic due-date field, so arbitrary issues are not treated as calendar events automatically.

When a user creates an issue from Iseol's schedule UI, Iseol creates both the GitHub issue and calendar event and stores an explicit `issue <-> calendarEvent` mapping. Updates initiated through Iseol can therefore keep the pair synchronized safely.

Webhook or polling events must be idempotent. A stable external key based on repository, item type, item number, and project id prevents duplicate events.

## Pull Request Review Trigger
Automatic review runs for pull request events `opened`, `reopened`, and `synchronize`. A review state key of repository + PR number + HEAD SHA is persisted so the same revision is never reviewed twice.

The reviewer fetches changed files and patches, excludes generated/vendor/lock files where appropriate, builds a bounded review context, then sends only relevant diff context to the AI provider.

## Gemini-Style Review Output
The GitHub PR must remain clean. The bot should resemble Gemini Code Assist rather than a verbose scoring dashboard.

The top-level review contains:
- A short `이설 Code Review` heading.
- A 2-5 bullet summary of the most important findings.
- A compact note when no actionable problems were found.
- No numeric category score table in the PR.
- No repeated restatement of the PR description.

Inline comments are created only when all of the following are true:
- The finding points to a changed line in the PR diff.
- The issue is actionable and materially useful.
- Confidence is high enough to avoid speculative noise.
- An equivalent comment has not already been posted for the same HEAD SHA.

Inline comments use short sections: severity/category, explanation, and an optional concise suggestion. Large architectural discussion belongs in the summary, not dozens of line comments.

A normal review should aim for 0-5 inline comments. Hard safety/correctness defects may exceed that limit only when the issues are distinct and independently actionable.

## AI Review Schema
The model output is parsed into a strict internal structure containing:
- summary
- findings[]
- file path
- line or diff position
- severity (`critical`, `major`, `minor`)
- category (`correctness`, `security`, `performance`, `maintainability`)
- confidence
- explanation
- optional suggested replacement

Invalid, out-of-diff, duplicate, or low-confidence findings are discarded before posting to GitHub.

## Provider Boundary
Create a provider-independent review interface. The first implementation may use Gemini, but GitHub posting logic must consume only normalized internal review results. This keeps future model changes isolated.

## GitHub Posting Rules
Post a single GitHub pull request review for each HEAD SHA. Inline comments are attached to the same review where possible. If no actionable finding exists, post one concise approval-style informational summary rather than a large empty template.

The bot must never block merges automatically in the first version. It provides review feedback only. Branch protection decisions remain with the repository maintainers.

## Discord Review Notifications
Discord receives only a compact notification in the relevant frontend/backend project log channel when a review completes or fails. Detailed findings remain on GitHub. This avoids duplicating the full review in two places.

## State Model
Extend `StoredProject` with optional calendar identifiers. Review deduplication and issue/calendar mappings should live in dedicated data files or focused persistence services rather than making `projects.json` a general event database.

No API keys, OAuth refresh tokens, access tokens, GitHub secrets, or AI credentials are stored in project data.

## Error Handling
Calendar, GitHub, and AI failures are isolated. A failed AI review must not interrupt Discord event handling. A failed calendar synchronization logs an actionable error and reports failure only to the invoking user or relevant project channel.

External API retries use bounded backoff for transient 429/5xx responses. Authentication/permission errors fail immediately with clear configuration diagnostics.

## Testing
Add automated tests for pure/domain behavior before implementation. At minimum cover:
- calendar mapping creation/update/delete semantics
- idempotent issue/milestone synchronization
- PR HEAD SHA deduplication
- diff changed-line validation
- AI response schema validation and low-confidence filtering
- duplicate inline finding collapse
- compact review rendering
- zero-finding review rendering

Run the complete test suite and `npm run build` before each subsystem is considered complete.

## Delivery Order
Implement in three independently testable slices:
1. Google Calendar project channel and Discord schedule controls.
2. GitHub issue/milestone calendar synchronization.
3. Gemini-style pull request review engine and GitHub review posting.

Each slice should be committed separately and must preserve existing bot behavior.

## Non-Goals for This Iteration
- Migrating the entire integration to a GitHub App.
- Automatically blocking or merging pull requests.
- Mirroring every GitHub issue into Calendar.
- Posting numeric code quality scores into pull requests.
- Storing full AI prompts/responses indefinitely.
