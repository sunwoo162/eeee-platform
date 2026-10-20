# Iseol IMPLEMENT PATCH_FRAME_V1 Design

## Problem
IMPLEMENT currently requires the model to serialize a large nested JSON result containing a unified diff. Repeated live runs fail with malformed object JSON before patch validation or Desktop dispatch.

## Evidence
Desktop execution and browser lifecycle are healthy through PLAN and into IMPLEMENT. Responses are complete-looking JSON objects, but bounded diagnostics repeatedly show `missing-comma-object` in the middle of the response. No usable `patchText` reaches validation.

## Goals
Reduce model-authored JSON syntax in IMPLEMENT while preserving strict patch and Desktop safety checks, deterministic recovery, and bounded diagnostics.

## Non-goals
This design does not change CONTEXT, ANALYZE, or PLAN; patch validation; retry budgets; browser ownership; Desktop eligibility; or Tasks 2–10.

## Old IMPLEMENT contract
IMPLEMENT requested one structured JSON object with common result fields, a PROPOSE_PATCH intent, redundant stage/type metadata, and a complete unified diff in the escaped `patchText` string. Legacy appendix parsing and structured `patchText` reading remain in the current reader for compatibility during migration.

## New PATCH_FRAME_V1 contract
IMPLEMENT must return exactly:

```text
ISEOL_PATCH_V1
<raw unified diff through EOF>
```

The header is the exact first line and occurs only as the transport header. The payload is non-empty raw unified diff text through EOF. There is no closing marker. Leading prose is rejected. Marker-like text inside the payload is ordinary patch text because framing ends only at EOF. CRLF is normalized to LF using the existing patch policy before validation.

## Stage-aware parsing architecture
The reasoning executor supplies an explicit result contract: structured JSON for CONTEXT, ANALYZE, and PLAN; `patch-frame-v1` for IMPLEMENT. The browser driver receives that contract and invokes only the corresponding parser. It never globally guesses between JSON and patch framing. A patch frame received for another stage is rejected.

## Detailed data flow
The completed assistant response is selected using the existing baseline and stability gates. For IMPLEMENT, the stage-aware extractor verifies the first line, extracts the remaining bytes, applies deterministic newline normalization, and rejects empty or duplicate framing. The extracted payload is passed unchanged (after policy normalization) to the existing strict unified-diff validator. Only a validated payload is converted into the internal PROPOSE_PATCH intent with the runtime-owned run/stage/intent identity and target path data. The normal Desktop intent compiler and validator then construct the dispatch pack.

## Prompt and correction behavior
Initial and correction IMPLEMENT prompts request only PATCH_FRAME_V1, with the exact header on the first line and a raw git-apply-compatible diff through EOF. They forbid JSON, prose, fences, closing markers, and additional control fields. Other stages retain their existing JSON instructions.

## Validation ordering
1. Confirm stage contract is `patch-frame-v1`.
2. Validate exact first-line header and framing.
3. Enforce bounded response and non-empty payload.
4. Normalize line endings according to existing policy.
5. Run existing path, header, hunk, count, and apply compatibility validation.
6. Construct the runtime-owned PROPOSE_PATCH intent.
7. Run existing Desktop intent validation and safety guards.
8. Dispatch through the existing Desktop Agent lease/idempotency path.

No unvalidated payload reaches intent construction or Desktop.

## Internal Desktop intent construction
IMPLEMENT semantics determine the single PROPOSE_PATCH operation. Runtime supplies the intent identifier, stage, run correlation, and target information. The model supplies only the raw diff payload. The resulting intent is indistinguishable from a validated structured intent to downstream validators.

## Compatibility and migration
New IMPLEMENT prompts use PATCH_FRAME_V1 exclusively. The reader retains a bounded legacy compatibility path for persisted or in-flight sessions that explicitly use the prior structured JSON or appendix contract. Compatibility is selected only when the persisted contract says legacy; it is never inferred from arbitrary text. Legacy output is still subject to the same strict patch validator. Legacy generation is not advertised in new prompts and will be removable after persisted legacy runs are no longer supported.

## Error and recovery semantics
Malformed headers, empty payloads, duplicate headers, unexpected trailing framing, and strict diff failures are typed retryable structured-result failures with safe categories. Recovery preserves the stage contract and does not reinterpret a patch frame as JSON. Existing bounded turn, supervision, and runtime ownership budgets remain unchanged. Durable Run state remains recoverable after exhaustion.

## Safe diagnostics
Parser diagnostics record only stage, contract type, generation/session correlation, conversation identity presence, header classification, payload empty/non-empty, response length bucket, and bounded validation category. Patch contents, prompts, responses, DOM, URLs, credentials, and chain-of-thought are never persisted.

## Security boundaries
The payload is untrusted input. Existing path safety, unified-diff syntax, hunk count, apply compatibility, workspace, lease, and Desktop authorization checks remain mandatory. EOF framing does not grant execution capability and cannot bypass intent validation.

## Test strategy
RED tests cover exact header acceptance, missing/duplicate headers, leading prose, empty payloads, multiline and marker-like patch content, deterministic newline handling, strict malformed-diff rejection, identical correction contracts, rejection of patch frames outside IMPLEMENT, unchanged JSON stages, runtime-owned intent construction, safe diagnostics, bounded recovery, and restart compatibility. Legacy fixtures prove the bounded read path remains available without being requested.

## Rollout
Land the contract and parser with focused tests, then use one fresh topology-controlled live smoke. Inspect safe diagnostics before any further behavior change. Existing legacy sessions remain readable; new sessions use PATCH_FRAME_V1.

## Task 1 acceptance criteria
Task 1 may advance only after a fresh normal-user smoke creates one prototype candidate, completes the canonical Run, verifies restart identity with `restart=verified`, and exits with code 0. No Tasks 2–10 work begins before that result.
