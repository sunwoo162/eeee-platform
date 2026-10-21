# Gleave Architecture

`Gleave` is one local-first open-source project. EEEE, ISEOL, and ClaimLatch are internal parts of that project, not three products the user must operate separately.

## Product boundary

```text
사용자 요청
   ↓
EEEE Assistant Kernel
   ├─ 상황·의도 해석
   ├─ 비휘발성 기억 검색
   ├─ 최적 capability·connector 선택
   ├─ 계획·승인·자동화
   └─ 사용자에게 결과 보고
          ↓
   Project 요청일 때만
          ↓
Unified Project Runtime
   ├─ Project Profile / revision
   ├─ local workspace / GitHub
   ├─ ISEOL project execution
   ├─ Notion project documentation
   ├─ Google Calendar schedule
   ├─ Desktop local host / Mobile remote bridge
   └─ project memory / QA baseline
          ↓
ISEOL
   ├─ task decomposition
   ├─ dynamic Agent teams
   ├─ parallel execution and handoff
   ├─ independent QA
   └─ integration / release
          ↓
Global Trust Layer
   ├─ ClaimLatch integration profile v0.2.0
   ├─ deterministic verification
   ├─ evidence ledger
   ├─ release gate
   └─ memory promotion gate
```

## EEEE chooses the tool

EEEE is the top-level personal assistant. The request is not assumed to be a development request.

| User intent | EEEE capability | Connected tool |
|---|---|---|
| 일정, 약속, 알림, 루틴 | `personal-secretary` | Google Calendar / local scheduler |
| 앱, 서비스, 기능, 프로젝트 | `project-execution` | Project Runtime + ISEOL |
| 문서, 정보, 요약, 검색 | `knowledge-documents` | local documents / memory |
| 문서, 결정, 진행 기록 | `knowledge-documents` | Notion adapter |
| 바탕화면, 휴대폰, 알림 | `presence` | Desktop widget / Mobile bridge |

Capabilities are registered through a descriptor and selected by the EEEE router. A new capability does not require adding another project-specific branch to the kernel.

## One project creation flow

`ProjectProvisioner` turns one natural-language request into one durable Project Runtime.

1. Issue a stable `projectId` and current `projectRevision`.
2. Parse goal, scope, constraints, schedule, acceptance criteria, and user preferences.
3. Retrieve matching EEEE memories and QA baselines.
4. Create the local workspace and Project Profile.
5. Compose the ISEOL project team and task decomposition policy.
6. Prepare Notion, Calendar, GitHub CI/Review, Desktop local host, and Mobile bridge plans.
7. Mark missing credentials as `awaiting_configuration`, never as completed.
8. Persist the profile, connector states, provenance, and idempotency keys in local SQLite.

Low-risk inferred values can be filled automatically. High-impact values such as public messages, deletion, deployment, or external writes remain planned until policy and ClaimLatch approval allow them.

## Local knowledge documents

The `knowledge-documents` capability is local and bounded. Explicit commands such
as `문서 저장해줘: 제목` followed by the document body, `문서 검색해줘: 검색어`,
and `문서 요약해줘: 검색어` persist, search, or summarize text in the same local
SQLite database used by EEEE. Document records are separate from user/project
memory and conversation turns. Search results and deterministic summaries include
the document ID and content hash as a source reference; an unavailable language
model never becomes a fabricated summary. Empty or ambiguous document commands
return a blocked clarification instead of selecting a project execution lane.

## ISEOL project-execution loop

ISEOL is an internal Harness Coordinator, not a required Discord bot. It creates the Agent team, splits the work, routes tasks, runs integration and independent QA, and records the outcome for EEEE. Project specifications, decisions, and execution logs belong in the Notion project workspace.

## GitHub CI and code-review loop

For each configured repository ISEOL installs or verifies the review workflow, collects the CI artifact for the exact pull-request head revision, filters findings to changed lines, merges duplicate CI findings, and posts the review result back to GitHub. The result is recorded as project evidence and passed through independent QA and ClaimLatch before it can become EEEE memory. No Discord channel or bot notification is required.

```text
GitHub PR / CI artifact
        ↓ exact repository + PR + head SHA
ISEOL review collector
        ↓ changed-line filter + finding aggregation
GitHub inline review + review summary
        ↓
ISEOL independent QA + ClaimLatch + Release Gate
```

The bot can recommend or block a change, but a code-review PASS is not release approval. Release still requires deterministic QA evidence and a ClaimLatch result for the same `projectId` and revision; only that combined outcome may become EEEE project memory.

## ClaimLatch placement

ClaimLatch is a cross-cutting trust service, not another Agent and not only a final QA step.

- EEEE answer/report gate: verifies AI claims before presenting them as trusted.
- Action gate: verifies Notion, Calendar, GitHub, deployment, and message actions before side effects.
- ISEOL result gate: verifies Agent reports and outcome identity.
- Release gate: combines ClaimLatch, deterministic verification, and independent QA for one project/revision.
- Memory promotion gate: only a completed, independently verified, ClaimLatch-PASS outcome can create trusted memory.

ClaimLatch and deterministic QA answer different questions:

- ClaimLatch asks whether an AI claim or requested action satisfies evidence and policy.
- Deterministic QA asks whether the actual command, file, test, artifact, and revision prove the result.
- Release Gate requires both to agree on the same project identity and revision.

The platform integration profile is `claimlatch-v0.2.0`. Audit records also preserve the actual bundled engine version separately; this is currently `0.3.86` in `packages/claimlatch/package.json` and must be resolved explicitly in the release manifest.

## Local-first operation

The local EEEE process and SQLite database are the source of truth. No EEEE login or hosted control plane is required.

- Desktop is the default local control surface and the only source of truth.
- Mobile is a separately deployable remote client. It pairs to Desktop, forwards EEEE commands, and receives live state/events; it does not run the database, Agents, or ClaimLatch.
- Notion, Calendar, and GitHub are optional connectors using credentials supplied by the user. ISEOL is local and ready by default; Discord is not a core connector.
- Missing connectors remain inspectable as `planned` or `awaiting_configuration`.
- Connector operations use project identity, revision, audit events, and idempotency keys.

## Repository map

```text
apps/eeee/                      EEEE kernel, API, memory, trust, local runtime
apps/desktop/                   Desktop deployment target and widget packaging boundary
apps/mobile/                    Mobile thin-client deployment target
packages/iseol                  project execution and Agent organization
packages/claimlatch             bundled ClaimLatch engine
integrations/contracts          versioned cross-runtime schemas
integrations/claimlatch-adapter local ClaimLatch HTTP boundary
docs/                           architecture, operations, specs, plans
scripts/                        local verification and release checks
```

## Desktop/Mobile deployment boundary

Desktop and Mobile are separate deployment targets while remaining part of the
same Gleave product contract.

```text
Desktop
  ├─ EEEE API + SQLite + local memory
  ├─ ISEOL Agent execution + CI/review evidence
  ├─ ClaimLatch + deterministic QA + release gate
  └─ Mobile Bridge
       ├─ short-lived pairing code
       ├─ hashed device token
       ├─ remote assistant command
       └─ SSE live events
              ▲
              │ paired local network / approved tunnel
Mobile ───────┘ thin remote client
```

Project documents and review evidence are durable Desktop records. Notion sync
uses `POST /api/projects/{projectId}/documents/sync`; ISEOL review delivery uses
`POST /api/projects/{projectId}/evidence/github-review` with the versioned
`github-review-result.v1` contract. Both external writes pass through the
ClaimLatch trust boundary before persistence or provider execution.

The Desktop shell calls `POST /api/assistant/route` as the primary local
assistant entrypoint, then reads `GET /api/desktop/state` and
`GET /api/desktop/events` for the redacted Project Runtime, ClaimLatch, and
lifecycle view. It can issue a short-lived Mobile pairing code through
`POST /api/desktop/pairing/code`; the code is not an access token.

The Mobile client calls `POST /api/mobile/assistant/route` for the same EEEE
secretary and project capabilities available on Desktop, reads
`GET /api/mobile/state` for the current snapshot, and subscribes to
`GET /api/mobile/events/stream` for live progress. Pairing is local and
user-initiated; the Desktop never exposes its provider tokens or database to
Mobile.

The detailed requirements and implementation sequence are in [`2026-10-06-eeee-personal-assistant-platform-design.md`](../superpowers/specs/2026-10-06-eeee-personal-assistant-platform-design.md) and [`2026-10-06-eeee-personal-assistant-platform-plan.md`](../superpowers/plans/2026-10-06-eeee-personal-assistant-platform-plan.md).
