# EEEE Hybrid Memory and Provider Routing Design

## Goal

Make EEEE a general personal assistant whose durable, user-specific memory is
owned by EEEE, while simple conversation uses a fast local model and complex
tool/project work can use the ChatGPT Web bridge in the background.

## Decisions

- `MemoryStore` is the canonical memory source. Local AI, ChatGPT Web, ISEOL,
  and plugins never own independent user memory.
- Every provider receives a bounded `MemoryContextPacket`, not the complete
  memory database or raw activity history.
- Explicit preferences and high-confidence repeated preferences may be saved
  automatically. Secrets, credentials, and one-off requests are excluded.
- General conversation uses the local provider when configured and healthy.
  If it is unavailable, EEEE may use the configured ChatGPT Web provider.
- Project execution and specialist agent work remain ISEOL-owned and may use
  ChatGPT Web; ClaimLatch and QA remain the release gate.
- Provider failures are visible and truthful. No provider may be represented as
  successful when it returned unavailable, blocked, or invalid output.

## Routing policy

| Request | Preferred path | Fallback |
|---|---|---|
| greeting, short question, preference lookup | local | ChatGPT Web |
| memory extraction/search | EEEE local services | none |
| optional plugin invocation | plugin + local orchestration | ask to connect |
| project/development request | ISEOL + ChatGPT Web/local coding runtime | blocked with reason |
| high-risk external side effect | plugin/provider after approval and ClaimLatch | blocked |

## Privacy boundary

Memory is local by default. The packet contains only relevant active records,
stable preferences, and non-sensitive summaries. Secret-like values are never
sent to a remote provider. The existing memory lifecycle and ClaimLatch gates
remain authoritative for promoted project memories.

## Acceptance criteria

1. A reopened EEEE process can retrieve the same user preference and expose it
   to either provider through the same packet.
2. A simple conversation selects local-first without requiring GPT Web.
3. A complex/project request does not silently downgrade to a fake success.
4. Provider selection and memory packet contents are deterministic and tested.
5. Existing EEEE, ISEOL, ClaimLatch, desktop, and mobile tests remain green.
