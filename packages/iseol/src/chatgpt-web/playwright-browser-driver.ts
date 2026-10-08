import {
  ChatGptWebAuthenticationRequiredError,
  ChatGptWebSessionLostError,
  ChatGptWebTemporarilyLimitedError,
  ChatGptWebConversationLimitError,
  ChatGptWebUsageLimitError,
  ChatGptWebStructuredResultError,
} from "./browser-adapter.js";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import type { ChatGptWebResultContract, ChatGptWebSessionProbe } from "./browser-adapter.js";
import type { ChatGptBrowserDriver } from "./production-browser-adapter.js";
import { classifyChatGptBrowserOperationFailure } from "./production-browser-adapter.js";
import type { PlaywrightBrowserDriverConfig } from "./playwright-browser-config.js";
import { createPlaywrightBrowserBackend, getAssistantTextReadDiagnostic, type PlaywrightBrowserBackend } from "./playwright-browser-backend.js";
import { patchRejectionDiagnostic } from "./patch-diagnostics.js";
import { appendDiagnosticLine, createResponseReadDiagnosticStore, type ResponseReadDiagnosticStage, type ResponseReadDiagnosticStore } from "./request-diagnostics.js";

export type { PlaywrightBrowserBackend } from "./playwright-browser-backend.js";

const ROOT = "https://chatgpt.com/";
const REF = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$/;
const POLL_MS = 100;
const RESULT_SETTLE_MS = 750;
const NEW_CONVERSATION_REF_TIMEOUT_MS = 30_000;
const COMPOSER_READY_TIMEOUT_MS = 15_000;
const MAX_STRUCTURED_RESULT_BYTES = 262_144;

type DriverDeps = {
  backend?: PlaywrightBrowserBackend;
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
};

function conversationFrom(url: string): string | undefined {
  try {
    const parsed = new URL(url);
    if (parsed.origin !== "https://chatgpt.com") return undefined;
    const match = decodeURIComponent(parsed.pathname).match(/^\/c\/([^/]+)\/?$/);
    return match?.[1] && REF.test(match[1]) ? match[1] : undefined;
  } catch { return undefined; }
}

function isCanonicalNewPage(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.origin === "https://chatgpt.com" && parsed.pathname === "/" && !parsed.search && !parsed.hash;
  } catch { return false; }
}
function authUrl(url: string): boolean {
  return /\/((auth\/)?login|signup|sign-up)(\/|$)/i.test(url);
}
function lost(message: string): never {
  throw new ChatGptWebSessionLostError(message, classifyChatGptBrowserOperationFailure(new Error(message)));
}
function structured(message: string, diagnostic?: Record<string, string | boolean>): never { throw new ChatGptWebStructuredResultError(message, diagnostic); }
function responseSha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}
function responseLengthBucket(value: string): "empty" | "short" | "medium" | "large" | "oversize" {
  const bytes = Buffer.byteLength(value, "utf8");
  return bytes === 0 ? "empty" : bytes < 256 ? "short" : bytes < 4096 ? "medium" : bytes <= MAX_STRUCTURED_RESULT_BYTES ? "large" : "oversize";
}
function parserTransformShape(source: string, candidate: string, codeFenceUnwrapped: boolean): Record<string, string> {
  return {
    parserInputLengthBucket: responseLengthBucket(source),
    candidateLengthBucket: responseLengthBucket(candidate),
    trimChanged: source === source.trim() ? "no" : "yes",
    codeFenceUnwrapped: codeFenceUnwrapped ? "yes" : "no",
  };
}
function jsonSyntaxShape(text: string, error: unknown): Record<string, string | boolean> {
  const message = error instanceof Error ? error.message : "";
  const position = Number(message.match(/position\s+(\d+)/i)?.[1] ?? NaN);
  const at = Number.isFinite(position) ? Math.min(position, text.length) : -1;
  const prefix = at >= 0 ? text.slice(0, at) : text;
  let inString = false; let escaped = false; let depth = 0;
  const stack: Array<"object" | "array"> = [];
  for (const ch of prefix) {
    if (inString) { if (escaped) escaped = false; else if (ch === "\\") escaped = true; else if (ch === '"') inString = false; continue; }
    if (ch === '"') inString = true;
    else if (ch === "{" || ch === "[") { depth += 1; stack.push(ch === "{" ? "object" : "array"); }
    else if (ch === "}" || ch === "]") { depth = Math.max(0, depth - 1); stack.pop(); }
  }
  const next = at >= 0 ? text[at] : undefined;
  const lower = message.toLowerCase();
  const before = at >= 0 ? text.slice(0, at) : text;
  const singleQuotePresent = text.includes("'");
  const bareAlphaRunDetected = /[A-Za-z]{2,}/.test(at >= 0 ? text.slice(Math.max(0, at - 16), Math.min(text.length, at + 16)) : "");
  const objectKey = /\{\s*[A-Za-z_][A-Za-z0-9_]*\s*$/.test(before);
  const afterColon = /:\s*$/.test(before);
  const afterValue = /(?:true|false|null|\d+|"(?:[^"\\]|\\.)*")\s*$/.test(before);
  const activeContainer = stack.at(-1) ?? "root";
  const parseFailureClass = objectKey && activeContainer === "object" ? "unquoted-property-name"
    : singleQuotePresent && next === "'" ? "single-quoted-string"
      : afterColon && bareAlphaRunDetected ? "bareword-value"
        : afterValue && next !== "," && next !== "}" && next !== "]" ? (activeContainer === "array" ? "missing-comma-array" : activeContainer === "object" ? "missing-comma-object" : "unexpected-value-token")
          : /unexpected end|end of json|unterminated/i.test(lower)
    ? "unexpected-end"
    : /escape/i.test(lower) ? "invalid-string-escape"
      : /number/i.test(lower) ? "invalid-number"
        : /unexpected token/i.test(lower) && next === "," ? "unexpected-comma"
          : /unexpected token/i.test(lower) ? "unexpected-token-in-value" : "other-json-syntax";
  const lexicalContext = inString ? "string" : /[,:]/.test(prefix.at(-1) ?? "") ? "delimiter" : "unknown";
  const containerContext = activeContainer;
  const expectedToken = objectKey ? "object-key" : afterColon ? "value" : afterValue ? (activeContainer === "array" ? "comma-or-array-end" : activeContainer === "object" ? "comma-or-object-end" : "end-of-document") : "unknown";
  return {
    parseFailurePositionBucket: at < 0 ? "unknown" : at < text.length * .1 ? "early" : at > text.length * .9 ? "late" : "middle",
    parseFailureClass,
    lexicalContext,
    insideStringAtFailure: inString ? "yes" : "no",
    nestingDepthBucket: depth < 3 ? "shallow" : depth < 8 ? "medium" : "deep",
    nearbyCharacterClass: next === '"' ? "quote" : next === "\\" ? "backslash" : next === "," ? "comma" : next === ":" ? "colon" : next === "{" || next === "}" ? "brace" : next === "[" || next === "]" ? "bracket" : /\d/.test(next ?? "") ? "digit" : /[A-Za-z]/.test(next ?? "") ? "alpha" : /\s/.test(next ?? "") ? "whitespace" : "other",
    containerContext,
    expectedToken,
    tokenClassAtFailure: next === '"' ? "quote" : next === "'" ? "single-quote" : next === ":" ? "colon" : next === "," ? "comma" : /[A-Za-z]/.test(next ?? "") ? "alpha" : /\d/.test(next ?? "") ? "digit" : "other",
    singleQuotePresent: singleQuotePresent ? "yes" : "no",
    bareAlphaRunDetected: bareAlphaRunDetected ? "yes" : "no",
  };
}
function jsonShape(text: string, error: unknown, extraction: Record<string, string | boolean> = {}): Record<string, string | boolean> {
  const t = text.trim(); const opens = (t.match(/\{/g) ?? []).length; const closes = (t.match(/\}/g) ?? []).length;
  const brackets = (t.match(/\[/g) ?? []).length; const closeBrackets = (t.match(/\]/g) ?? []).length;
  const msg = error instanceof Error ? error.message : "";
  return { diagnosticCategory: "response-envelope-malformed", rejectionClass: "json-syntax-error", parserInputReceived: true, responsePresent: true, responseSha256: responseSha256(t), responseLengthBucket: responseLengthBucket(t), startsWithObjectToken: t.startsWith("{"), endsWithObjectToken: t.endsWith("}"), startsWithArrayToken: t.startsWith("["), endsWithArrayToken: t.endsWith("]"), markdownFencePresent: /^```/.test(t), leadingWrapperPresent: !/^[\[{]/.test(t), trailingWrapperPresent: !/[\]}]$/.test(t), topLevelBraceBalance: opens === closes ? "balanced" : opens > closes ? "more-open" : "more-close", topLevelBracketBalance: brackets === closeBrackets ? "balanced" : brackets > closeBrackets ? "more-open" : "more-close", likelyTruncated: /end of json|unexpected end|unterminated/i.test(msg) ? "yes" : "unknown", ...jsonSyntaxShape(t, error), ...extraction };
}

function classifyBrowserFailure(error: unknown): never {
  if (
    error instanceof ChatGptWebAuthenticationRequiredError
    || error instanceof ChatGptWebSessionLostError
    || error instanceof ChatGptWebTemporarilyLimitedError
    || error instanceof ChatGptWebConversationLimitError
    || error instanceof ChatGptWebUsageLimitError
    || error instanceof ChatGptWebStructuredResultError
  ) throw error;
  throw new ChatGptWebSessionLostError("ChatGPT browser operation failed", classifyChatGptBrowserOperationFailure(error));
}

function boundedFailureClass(error: unknown): string {
  if (error instanceof ChatGptWebStructuredResultError) return "structured-result-parser-rejection";
  if (error instanceof ChatGptWebSessionLostError) return error.failureClass ?? "unknown";
  if (error instanceof ChatGptWebAuthenticationRequiredError) return "auth-or-login-page";
  if (error instanceof ChatGptWebTemporarilyLimitedError) return "temporary-limit";
  if (error instanceof ChatGptWebConversationLimitError) return "conversation-limit";
  if (error instanceof ChatGptWebUsageLimitError) return "usage-limit";
  return classifyChatGptBrowserOperationFailure(error);
}

function canonicalizeNewFilePatch(patch: string): string {
  const lines = patch.replaceAll("\r\n", "\n").split("\n");
  const trailingNewline = lines.at(-1) === "";
  if (trailingNewline) lines.pop();
  if (lines.filter((line) => line.startsWith("--- ")).length !== 1 || !lines.includes("--- /dev/null")) return patch;
  const hunkIndexes = lines.flatMap((line, index) => line.startsWith("@@ ") ? [index] : []);
  if (hunkIndexes.length !== 1) return patch;
  const hunkIndex = hunkIndexes[0]!;
  const match = lines[hunkIndex]!.match(/^@@ -0,0 \+(\d+)(?:,\d+)? @@(.*)$/);
  if (!match) return patch;
  let newCount = 0;
  for (let index = hunkIndex + 1; index < lines.length; index += 1) {
    const line = lines[index]!;
    if (line === "\\ No newline at end of file") continue;
    if (line.startsWith("diff --git ") || line.startsWith("--- ") || line.startsWith("+++ ") || line.startsWith("@@ ")) return patch;
    if (line.startsWith(" ") || line.startsWith("-")) return patch;
    if (!line.startsWith("+")) lines[index] = `+${line}`;
    newCount += 1;
  }
  lines[hunkIndex] = `@@ -0,0 +${match[1]},${newCount} @@${match[2] ?? ""}`;
  return lines.join("\n") + (trailingNewline ? "\n" : "");
}

function canonicalizeHunkBlankLineNoise(patch: string): string {
  const lines = patch.replaceAll("\r\n", "\n").split("\n");
  const trailingNewline = lines.at(-1) === "";
  if (trailingNewline) lines.pop();
  const output: string[] = [];
  let inHunk = false;
  for (const line of lines) {
    if (line.startsWith("@@ ")) inHunk = true;
    else if (inHunk && (line.startsWith("diff --git ") || line.startsWith("--- ") || line.startsWith("+++ "))) inHunk = false;
    if (inHunk && line === "") continue;
    output.push(line);
  }
  return output.join("\n") + (trailingNewline ? "\n" : "");
}

function validatePatchAppendixSyntax(patch: string): void {
  const lines = patch.replaceAll("\r\n", "\n").split("\n");
  if (lines.at(-1) === "") lines.pop();
  const diffHeaders = lines.filter((line) => line.startsWith("diff --git "));
  const oldHeaders = lines.filter((line) => line.startsWith("--- "));
  const newHeaders = lines.filter((line) => line.startsWith("+++ "));
  if (diffHeaders.length !== 1 || oldHeaders.length !== 1 || newHeaders.length !== 1) {
    structured("ChatGPT patch appendix must contain exactly one file diff");
  }
  let hunks = 0;
  let index = 0;
  while (index < lines.length) {
    const header = lines[index]!;
    if (!header.startsWith("@@ ")) { index += 1; continue; }
    const match = header.match(/^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@(?: .*)?$/);
    if (!match) structured("ChatGPT patch hunk header is invalid");
    const expectedOld = match[1] === undefined ? 1 : Number.parseInt(match[1], 10);
    const expectedNew = match[2] === undefined ? 1 : Number.parseInt(match[2], 10);
    let seenOld = 0;
    let seenNew = 0;
    hunks += 1;
    index += 1;
    while (index < lines.length && !lines[index]!.startsWith("@@ ")) {
      const line = lines[index]!;
      if (line === "\\ No newline at end of file") { index += 1; continue; }
      if (line.startsWith("diff --git ") || line.startsWith("--- ") || line.startsWith("+++ ")) {
        structured("ChatGPT patch appendix must contain exactly one file diff");
      }
      const prefix = line[0];
      if (prefix === " ") { seenOld += 1; seenNew += 1; }
      else if (prefix === "-") seenOld += 1;
      else if (prefix === "+") seenNew += 1;
      else structured("ChatGPT patch hunk body lines require a unified-diff prefix");
      index += 1;
    }
    if (seenOld !== expectedOld || seenNew !== expectedNew) {
      structured("ChatGPT patch hunk line counts do not match the hunk header");
    }
  }
  if (hunks === 0) structured("ChatGPT patch appendix must include at least one hunk");
}

function parsePatchMultipart(candidate: string): unknown | null {
  const firstNewline = candidate.indexOf("\n");
  if (firstNewline < 0) return null;
  const headerText = candidate.slice(0, firstNewline).trim();
  let header: any;
  try { header = JSON.parse(headerText); } catch { return null; }
  if (!header || typeof header !== "object" || Array.isArray(header)) structured("ChatGPT patch header must be one JSON object");
  let rest = candidate.slice(firstNewline + 1).replaceAll("\r\n", "\n");
  const blocks = new Map<string, string>();
  while (rest.trim()) {
    if (rest.startsWith("\n")) rest = rest.slice(1);
    const begin = rest.match(/^@@ISEOL_PATCH_BEGIN:([A-Za-z0-9][A-Za-z0-9._:-]{0,191})@@\n/);
    if (!begin?.[1]) structured("ChatGPT patch appendix begin marker is invalid");
    const id = begin[1];
    if (blocks.has(id)) structured("ChatGPT patch appendix id is duplicated");
    const bodyStart = begin[0].length;
    const endMarker = `\n@@ISEOL_PATCH_END:${id}@@`;
    const endAt = rest.indexOf(endMarker, bodyStart);
    if (endAt < 0) structured("ChatGPT patch appendix end marker is missing");
    blocks.set(id, rest.slice(bodyStart, endAt) + "\n");
    rest = rest.slice(endAt + endMarker.length);
  }
  const intents = Array.isArray(header.intents) ? header.intents : [];
  const used = new Set<string>();
  for (const intent of intents) {
    if (!intent || intent.kind !== "PROPOSE_PATCH") continue;
    const id = typeof intent.intentId === "string" ? intent.intentId : "";
    if (intent.patch !== `@@ISEOL_PATCH:${id}@@`) structured("ChatGPT patch placeholder does not match intent identity");
    const patch = blocks.get(id);
    if (patch === undefined) structured("ChatGPT patch appendix is missing");
    const canonicalPatch = canonicalizeHunkBlankLineNoise(canonicalizeNewFilePatch(patch));
    validatePatchAppendixSyntax(canonicalPatch);
    intent.patch = canonicalPatch;
    used.add(id);
  }
  if (blocks.size !== used.size) structured("ChatGPT patch appendix is not referenced by a PROPOSE_PATCH intent");
  return header;
}
function parseStructuredResult(text: string, legacyCompatibility = false, extraction: Record<string, string | boolean> = {}): unknown {
  if (Buffer.byteLength(text, "utf8") > MAX_STRUCTURED_RESULT_BYTES) structured("ChatGPT structured result exceeds the allowed size", { diagnosticCategory: "response-envelope-malformed", rejectionClass: "response-too-large", parserInputReceived: true, ...parserTransformShape(text, text.trim(), false) });
  const trimmed = text.trim();
  if (!trimmed) structured("ChatGPT structured result is empty", { diagnosticCategory: "response-envelope-missing", rejectionClass: "response-empty", parserInputReceived: true, responsePresent: false, ...parserTransformShape(text, trimmed, false) });
  let candidate = trimmed;
  let codeFenceUnwrapped = false;
  const fenced = trimmed.match(/^```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```$/i);
  if (fenced) { candidate = fenced[1]?.trim() ?? ""; codeFenceUnwrapped = true; }
  else if (trimmed.startsWith("```") || trimmed.endsWith("```")) structured("ChatGPT structured result fence is malformed", { diagnosticCategory: "response-envelope-malformed", rejectionClass: "markdown-fence-malformed", parserInputReceived: true, responsePresent: true, ...parserTransformShape(text, trimmed, false) });
  if (legacyCompatibility) {
    const multipart = parsePatchMultipart(candidate);
    if (multipart !== null) return multipart;
  }
  try {
    const parsed = JSON.parse(candidate);
    const intents = parsed && typeof parsed === "object" && Array.isArray((parsed as any).intents) ? (parsed as any).intents : [];
    if (!legacyCompatibility && intents.some((intent: any) => intent?.kind === "PROPOSE_PATCH")) {
      structured("ChatGPT structured JSON contract does not accept PROPOSE_PATCH payloads");
    }
    if (legacyCompatibility) {
      for (const intent of intents) {
        if (intent?.kind === "PROPOSE_PATCH" && typeof intent.patchText === "string") {
          const patchText = intent.patchText.replaceAll("\r\n", "\n");
          if (!patchText.trim()) structured("ChatGPT patch appendix is empty");
          validatePatchAppendixSyntax(patchText);
          intent.patch = patchText;
        }
      }
      if (intents.some((intent: any) => intent?.kind === "PROPOSE_PATCH" && typeof intent.patchText !== "string")) structured("ChatGPT PROPOSE_PATCH requires structured patchText payload");
    }
    return parsed;
  } catch (error) {
    if (error instanceof ChatGptWebStructuredResultError) throw error;
    return structured("ChatGPT structured result is not exactly one JSON value", jsonShape(candidate, error, { ...parserTransformShape(text, candidate, codeFenceUnwrapped), ...extraction }));
  }
}

export function parsePatchFrameV1(text: string): string {
  if (Buffer.byteLength(text, "utf8") > MAX_STRUCTURED_RESULT_BYTES) {
    structured("ChatGPT PATCH_FRAME_V1 result exceeds the allowed size", {
      diagnosticCategory: "patch-frame-format-failure",
      frameHeaderPresent: false,
      payloadEmpty: false,
    });
  }

  const normalized = text.replaceAll("\r\n", "\n");
  const headerEnd = normalized.indexOf("\n");

  if (headerEnd < 0 || normalized.slice(0, headerEnd) !== "ISEOL_PATCH_V1") {
    structured("ChatGPT PATCH_FRAME_V1 header is missing or invalid", {
      ...patchRejectionDiagnostic(text, "frame-missing"),
      diagnosticCategory: "patch-frame-format-failure",
      frameHeaderPresent: normalized.startsWith("ISEOL_PATCH_V1"),
      payloadEmpty: false,
    });
  }

  const payload = normalized.slice(headerEnd + 1);

  if (!payload.trim()) {
    structured("ChatGPT PATCH_FRAME_V1 payload is empty", {
      ...patchRejectionDiagnostic(text, "empty-patch"),
      diagnosticCategory: "patch-frame-format-failure",
      frameHeaderPresent: true,
      payloadEmpty: true,
    });
  }

  const trimmed = payload.trim();
  const fenced = trimmed.match(
    /^```diff[ \t]*\n([\s\S]*?)\n```$/i,
  );

  if (fenced) {
    const inner = fenced[1] ?? "";

    if (!inner.trim()) {
      structured("ChatGPT PATCH_FRAME_V1 fenced payload is empty", {
        ...patchRejectionDiagnostic(text, "empty-patch"),
        diagnosticCategory: "patch-frame-format-failure",
        frameHeaderPresent: true,
        payloadEmpty: true,
      });
    }

    return inner.endsWith("\n") ? inner : `${inner}\n`;
  }

  if (trimmed.startsWith("```") || trimmed.endsWith("```")) {
    structured("ChatGPT PATCH_FRAME_V1 diff fence is malformed", {
      ...patchRejectionDiagnostic(text, "malformed-frame"),
      diagnosticCategory: "patch-frame-format-failure",
      frameHeaderPresent: true,
      payloadEmpty: false,
    });
  }

  return payload;
}

export async function createPlaywrightChatGptBrowserDriver(
  config: Extract<PlaywrightBrowserDriverConfig, { enabled: true }>,
  deps?: DriverDeps,
): Promise<ChatGptBrowserDriver> {
  const backend = deps?.backend ?? await createPlaywrightBrowserBackend(config);
  const now = deps?.now ?? (() => Date.now());
  const sleep = deps?.sleep ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
  const submittedByTurn = new Map<string, string | undefined>();
  const inFlightByTurn = new Map<string, Promise<{ conversationRef?: string }>>();
  const pendingByConversation = new Map<string, { baselineAssistantCount: number }>();
  const turnKey = (conversationRef: string | undefined, sha: string) => JSON.stringify([conversationRef ?? null, sha]);
  const responseReadDiagnosticStore = config.lifecycleRoot ? createResponseReadDiagnosticStore(config.lifecycleRoot) : undefined;

  function createReadDiagnostic(requestId: string | undefined, startedAt: number) {
    if (!responseReadDiagnosticStore || !requestId || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$/.test(requestId)) return undefined;
    const started = new Set<ResponseReadDiagnosticStage>();
    const completed = new Set<ResponseReadDiagnosticStage>();
    const failed = new Set<ResponseReadDiagnosticStage>();
    let writes = Promise.resolve();
    const emit = (stage: ResponseReadDiagnosticStage, phase: "start" | "complete" | "failure", details: Record<string, unknown> = {}) => {
      const event = {
        requestId,
        stage,
        phase,
        at: new Date().toISOString(),
        elapsedMs: Math.max(0, now() - startedAt),
        ok: phase !== "failure",
        ...details,
      } as const;
      writes = writes.then(() => responseReadDiagnosticStore.record(event as any)).catch(() => undefined);
    };
    return {
      start(stage: ResponseReadDiagnosticStage, details: Record<string, unknown> = {}) {
        if (started.has(stage)) return;
        started.add(stage);
        emit(stage, "start", details);
      },
      complete(stage: ResponseReadDiagnosticStage, details: Record<string, unknown> = {}) {
        if (completed.has(stage)) return;
        completed.add(stage);
        emit(stage, "complete", details);
      },
      failure(stage: ResponseReadDiagnosticStage, error: unknown) {
        if (failed.has(stage)) return;
        failed.add(stage);
        const assistantTextDiagnostic = stage === "assistant-text" ? getAssistantTextReadDiagnostic(error) : undefined;
        emit(stage, "failure", {
          failureClass: boundedFailureClass(error),
          ...(assistantTextDiagnostic ? {
            assistantTextCallPoint: assistantTextDiagnostic.callPoint,
            assistantTextRetryable: assistantTextDiagnostic.retryable,
          } : {}),
        });
      },
    };
  }

  async function ensureAuthenticatedPage(url: string): Promise<void> {
    if (await backend.temporaryRestrictionCount() > 0) {
      try { await backend.dismissTemporaryRestriction?.(); } catch { /* restriction still wins */ }
      throw new ChatGptWebTemporarilyLimitedError("ChatGPT Web is temporarily rate limited");
    }
    if ((await backend.conversationLimitCount?.() ?? 0) > 0) throw new ChatGptWebConversationLimitError("ChatGPT conversation limit reached");
    if ((await backend.usageLimitCount?.() ?? 0) > 0) throw new ChatGptWebUsageLimitError("ChatGPT Web usage limit reached");
    const authCount = await backend.authenticationRequiredCount();
    if (authUrl(url) || authCount > 0) {
      throw new ChatGptWebAuthenticationRequiredError("ChatGPT authentication is required");
    }
  }

  async function authenticatedComposerCount(url: string): Promise<number> {
    await ensureAuthenticatedPage(url);
    return backend.composerCount();
  }

  async function waitForAuthenticatedComposer(): Promise<string> {
    const startedAt = now();
    while (true) {
      const url = await backend.currentUrl();
      const composerCount = await authenticatedComposerCount(url);
      if (composerCount === 1) return url;
      if (composerCount > 1) lost("Authenticated ChatGPT composer is missing or ambiguous");
      if (now() - startedAt >= COMPOSER_READY_TIMEOUT_MS) {
        lost("Authenticated ChatGPT composer is missing or ambiguous");
      }
      await sleep(POLL_MS);
    }
  }

  async function waitForNewConversationRef(): Promise<string> {
    const startedAt = now();
    while (true) {
      if (await backend.temporaryRestrictionCount() > 0) {
        try { await backend.dismissTemporaryRestriction?.(); } catch { /* restriction still wins */ }
        throw new ChatGptWebTemporarilyLimitedError("ChatGPT Web is temporarily rate limited");
      }
      if ((await backend.conversationLimitCount?.() ?? 0) > 0) throw new ChatGptWebConversationLimitError("ChatGPT conversation limit reached");
      if ((await backend.usageLimitCount?.() ?? 0) > 0) throw new ChatGptWebUsageLimitError("ChatGPT Web usage limit reached");
      const url = await backend.currentUrl();
      if (authUrl(url)) throw new ChatGptWebAuthenticationRequiredError("ChatGPT authentication is required");
      const actual = conversationFrom(url);
      if (actual && !actual.startsWith("WEB:") && !actual.startsWith("local-chatgpt:")) return actual;
      if (now() - startedAt >= NEW_CONVERSATION_REF_TIMEOUT_MS) {
        return lost("ChatGPT did not assign a canonical conversation identity after prompt submission");
      }
      await sleep(POLL_MS);
    }
  }

  async function openOrResumeConversation(input: { conversationRef?: string; prompt: string; promptSha256: string }) {
    try {
      const requested = input.conversationRef;
      if (requested && !REF.test(requested)) lost("Conversation identity is invalid");
      await backend.navigate(requested ? `${ROOT}c/${requested}` : ROOT);
      const url = await waitForAuthenticatedComposer();
      const actual = conversationFrom(url);
      if (requested) {
        if (actual !== requested) lost("ChatGPT conversation identity changed during navigation");
        return { conversationRef: requested };
      }
      if (actual) return { conversationRef: actual };
      if (isCanonicalNewPage(url)) return {};
      return lost("ChatGPT new conversation navigation drifted from the canonical page");
    } catch (error) { return classifyBrowserFailure(error); }
  }

  async function submitPrompt(input: { conversationRef?: string; prompt: string; promptSha256: string }) {
    if (!input.promptSha256) lost("Prompt identity is unavailable");
    const key = turnKey(input.conversationRef, input.promptSha256);
    if (submittedByTurn.has(key)) {
      const previous = submittedByTurn.get(key);
      return previous ? { conversationRef: previous } : {};
    }
    const existing = inFlightByTurn.get(key);
    if (existing) return existing;

    const operation = (async (): Promise<{ conversationRef?: string }> => {
      try {
        const beforeUrl = await backend.currentUrl();
        if (input.conversationRef) {
          if (!REF.test(input.conversationRef) || conversationFrom(beforeUrl) !== input.conversationRef) {
            lost("ChatGPT conversation identity changed before prompt submission");
          }
        } else if (!isCanonicalNewPage(beforeUrl)) {
          lost("ChatGPT new conversation identity is unavailable before prompt submission");
        }
        if (await authenticatedComposerCount(beforeUrl) !== 1) lost("Authenticated ChatGPT composer is missing or ambiguous");
        const baselineAssistantCount = await backend.assistantMessageCount();
        await backend.fillComposer(input.prompt);
        await backend.sendPrompt();

        const actual = input.conversationRef ?? await waitForNewConversationRef();
        if (conversationFrom(await backend.currentUrl()) !== actual) {
          lost("ChatGPT conversation identity changed after prompt submission");
        }
        submittedByTurn.set(key, actual);
        submittedByTurn.set(turnKey(actual, input.promptSha256), actual);
        pendingByConversation.set(actual, { baselineAssistantCount });
        return { conversationRef: actual };
      } catch (error) { return classifyBrowserFailure(error); }
    })();

    inFlightByTurn.set(key, operation);
    operation.then(
      () => { inFlightByTurn.delete(key); },
      () => { inFlightByTurn.delete(key); },
    );
    return operation;
  }

  async function readStructuredResult(input: { requestId?: string; conversationRef: string; timeoutMs: number; contract: ChatGptWebResultContract }): Promise<unknown> {
    const startedAt = now();
    const diagnostic = createReadDiagnostic(input.requestId, startedAt);
    const diagnosticFailure = (stage: ResponseReadDiagnosticStage, error: unknown) => diagnostic?.failure(stage, error);
    try {
      if (!REF.test(input.conversationRef)) {
        const error = new ChatGptWebSessionLostError("Conversation identity is invalid", "conversation-identity-changed");
        diagnosticFailure("conversation-identity", error);
        throw error;
      }
      if (!Number.isFinite(input.timeoutMs) || input.timeoutMs <= 0) {
        const error = new ChatGptWebSessionLostError("Structured result timeout is invalid", "response-timeout");
        diagnosticFailure("assistant-stability", error);
        throw error;
      }
      diagnostic?.start("pending-submission");
      const pending = pendingByConversation.get(input.conversationRef);
      if (!pending) {
        const error = new ChatGptWebSessionLostError("No pending ChatGPT submission is available for structured result reading", "pending-submission-missing");
        diagnosticFailure("pending-submission", error);
        throw error;
      }
      diagnostic?.complete("pending-submission");
      const baseline = pending.baselineAssistantCount;
      let stableText: string | null = null;
      let stableSince = startedAt;

      while (true) {
        diagnostic?.start("conversation-identity");
        let url: string;
        try {
          url = await backend.currentUrl();
          if (conversationFrom(url) !== input.conversationRef) {
            const error = new ChatGptWebSessionLostError("ChatGPT conversation identity changed while reading result", "conversation-identity-changed");
            diagnosticFailure("conversation-identity", error);
            throw error;
          }
          diagnostic?.complete("conversation-identity");
        } catch (error) {
          diagnosticFailure("conversation-identity", error);
          throw error;
        }

        diagnostic?.start("authentication-state");
        try {
          await ensureAuthenticatedPage(url);
          diagnostic?.complete("authentication-state");
        } catch (error) {
          diagnosticFailure("authentication-state", error);
          throw error;
        }

        diagnostic?.start("assistant-locator");
        let assistantCount: number;
        try {
          assistantCount = await backend.assistantMessageCount();
          diagnostic?.complete("assistant-locator", {
            assistantCount,
            baselineAssistantCount: baseline,
            awaitingAssistant: assistantCount <= baseline,
          });
        } catch (error) {
          diagnosticFailure("assistant-locator", error);
          throw error;
        }

        diagnostic?.start("generation-control");
        let generatingCount: number;
        try {
          generatingCount = await backend.generationControlCount();
          diagnostic?.complete("generation-control", { generationControlCount: generatingCount });
        } catch (error) {
          diagnosticFailure("generation-control", error);
          throw error;
        }

        let latestText: string | null = null;
        if (assistantCount > baseline) {
          diagnostic?.start("assistant-text", { assistantCount, baselineAssistantCount: baseline });
          try {
            latestText = await backend.latestAssistantText();
            diagnostic?.complete("assistant-text", { assistantCount });
          } catch (error) {
            diagnosticFailure("assistant-text", error);
            throw error;
          }
        }

        if (generatingCount === 0 && latestText?.trim()) {
          diagnostic?.start("assistant-stability");
          if (latestText === stableText) {
            if (now() - stableSince >= RESULT_SETTLE_MS) {
              diagnostic?.complete("assistant-stability", { generationControlCount: generatingCount });
              let domText: string | null = null;
              diagnostic?.start("dom-extraction");
              try {
                domText = await backend.latestAssistantDomText?.() ?? null;
                diagnostic?.complete("dom-extraction", {
                  domExtractionAttempted: true,
                  domExtractionSucceeded: Boolean(domText?.trim()),
                  responseLengthBucket: responseLengthBucket(domText?.trim() ?? ""),
                  responseSource: domText?.trim() ? "assistant-dom" : "assistant-copy",
                });
              } catch (error) {
                diagnosticFailure("dom-extraction", error);
                throw error;
              }

              diagnostic?.start("final-identity");
              try {
                const finalAssistantCount = await backend.assistantMessageCount();
                const finalLatestText = await backend.latestAssistantText();
                if (finalAssistantCount !== assistantCount || finalLatestText !== latestText) {
                  const error = new ChatGptWebSessionLostError("ChatGPT assistant message identity changed while reading result", "conversation-identity-changed");
                  diagnosticFailure("final-identity", error);
                  throw error;
                }
                diagnostic?.complete("final-identity", { assistantCount: finalAssistantCount });
              } catch (error) {
                diagnosticFailure("final-identity", error);
                throw error;
              }

              const extraction = {
                completionDetected: true,
                assistantSelection: "latest-after-baseline",
                responseSource: domText?.trim() ? "assistant-dom" : "assistant-copy",
                renderedRawMatch: domText?.trim() && responseSha256(latestText) === responseSha256(domText) ? "yes" : "no",
                renderedResponseSha256: responseSha256(latestText),
              } as const;

              if (domText?.trim()) {
                diagnostic?.start("response-parse");
                try {
                  pendingByConversation.delete(input.conversationRef);
                  let result: unknown;
                  if (input.contract === "structured-json") result = parseStructuredResult(domText, false, extraction);
                  else if (input.contract === "patch-frame-v1") result = parsePatchFrameV1(domText);
                  else if (input.contract === "legacy-structured-json") result = parseStructuredResult(domText, true, extraction);
                  else structured("ChatGPT result contract is unsupported");
                  diagnostic?.complete("response-parse", { responseSource: "assistant-dom", domExtractionAttempted: true, domExtractionSucceeded: true, responseLengthBucket: responseLengthBucket(domText) });
                  return result;
                } catch (error) {
                  diagnosticFailure("response-parse", error);
                  // Rendered markdown can consume unified-diff prefixes. Keep
                  // the lossless clipboard route as an explicit fallback for
                  // patch-bearing contracts only; structured JSON must fail
                  // closed rather than silently switch sources.
                  if (input.contract === "structured-json") throw error;
                }
              }

              diagnostic?.start("clipboard-fallback");
              let rawText: string | null;
              try {
                rawText = await backend.latestAssistantRawText();
                if (!rawText?.trim()) {
                  const error = new ChatGptWebSessionLostError("ChatGPT assistant source is unavailable", "assistant-response-extraction-failed");
                  diagnosticFailure("clipboard-fallback", error);
                  throw error;
                }
                diagnostic?.complete("clipboard-fallback", { responseSource: domText?.trim() ? "assistant-copy-fallback" : "assistant-copy", domExtractionAttempted: true, domExtractionSucceeded: Boolean(domText?.trim()), responseLengthBucket: responseLengthBucket(rawText) });
              } catch (error) {
                diagnosticFailure("clipboard-fallback", error);
                throw error;
              }
              pendingByConversation.delete(input.conversationRef);
              const copyExtraction = {
                ...extraction,
                responseSource: domText?.trim() ? "assistant-copy-fallback" : "assistant-copy",
                renderedRawMatch: responseSha256(latestText) === responseSha256(rawText) ? "yes" : "no",
              } as const;
              diagnostic?.start("response-parse");
              try {
                let result: unknown;
                if (input.contract === "structured-json") result = parseStructuredResult(rawText, false, copyExtraction);
                else if (input.contract === "patch-frame-v1") result = parsePatchFrameV1(rawText);
                else if (input.contract === "legacy-structured-json") result = parseStructuredResult(rawText, true, copyExtraction);
                else structured("ChatGPT result contract is unsupported");
                diagnostic?.complete("response-parse", { responseSource: copyExtraction.responseSource, domExtractionAttempted: true, domExtractionSucceeded: Boolean(domText?.trim()), responseLengthBucket: responseLengthBucket(rawText) });
                return result;
              } catch (error) {
                diagnosticFailure("response-parse", error);
                throw error;
              }
            }
          } else {
            stableText = latestText;
            stableSince = now();
          }
        } else {
          stableText = null;
          stableSince = now();
        }

        const elapsed = now() - startedAt;
        if (elapsed >= input.timeoutMs) {
          const error = new ChatGptWebSessionLostError("ChatGPT structured result timed out", "response-timeout");
          diagnosticFailure("assistant-stability", error);
          throw error;
        }
        await sleep(Math.min(POLL_MS, Math.max(1, input.timeoutMs - elapsed)));
      }
    } catch (error) { return classifyBrowserFailure(error); }
  }

  async function probeConversation(conversationRef: string): Promise<ChatGptWebSessionProbe> {
    if (!REF.test(conversationRef)) return "lost";
    try {
      const url = await backend.currentUrl();
      const restrictionCount = await backend.temporaryRestrictionCount();
      if (restrictionCount > 0) { try { await backend.dismissTemporaryRestriction?.(); } catch {} return "temporarily-limited"; }
      if ((await backend.conversationLimitCount?.() ?? 0) > 0) return "conversation-exhausted";
      if ((await backend.usageLimitCount?.() ?? 0) > 0) return "usage-limited";
      const composerCount = await backend.composerCount();
      const authCount = await backend.authenticationRequiredCount();
      if (authUrl(url) || authCount > 0) return "auth-required";
      if (conversationFrom(url) !== conversationRef || composerCount !== 1) return "lost";
      return "ready";
    } catch { return "lost"; }
  }

  return {
    openOrResumeConversation,
    submitPrompt,
    readStructuredResult,
    probeConversation,
    async closeConversation(conversationRef) {
      if (!REF.test(conversationRef)) lost("Conversation identity is invalid");
      await backend.closeOwnedPage();
      pendingByConversation.delete(conversationRef);
      for (const [key, submittedConversationRef] of submittedByTurn) {
        if (submittedConversationRef === conversationRef) submittedByTurn.delete(key);
      }
    },
    async recordParserDiagnostic(input) {
      if (!config.lifecycleRoot) return;
      const category = input.diagnostic?.diagnosticCategory ?? (/structured result is not exactly one JSON value|structured result fence is malformed/i.test(input.message) ? "response-envelope-malformed"
        : /structured result is empty/i.test(input.message) ? "response-envelope-missing"
          : /patchText payload/i.test(input.message) ? "patch-text-missing"
            : /patch appendix is empty/i.test(input.message) ? "patch-text-empty"
              : /begin marker is invalid|placeholder/i.test(input.message) ? "appendix-marker-malformed"
        : /end marker is missing|appendix is missing/i.test(input.message) ? "appendix-marker-missing"
          : /appendix.*empty/i.test(input.message) ? "appendix-empty"
            : /hunk.*header/i.test(input.message) ? "hunk-header-invalid"
              : /line counts/i.test(input.message) ? "hunk-count-mismatch"
                : /diff.*header|exactly one file diff/i.test(input.message) ? "diff-header-invalid"
                  : /body lines require/i.test(input.message) ? "unsupported-diff-shape"
                : /not referenced|must be one JSON object/i.test(input.message) ? "parser-contract-violation" : "unknown-safe-parser-rejection");
      const phase = /not exactly one JSON value|fence is malformed/i.test(input.message) ? "json-decode"
        : /structured result is empty/i.test(input.message) ? "response-envelope"
          : /PROPOSE_PATCH requires/i.test(input.message) ? "intent-specific-shape"
            : /patch appendix|patch hunk|unified-diff/i.test(input.message) ? "structured-patch-validation" : "contract-validation";
      const file = resolve(config.lifecycleRoot, "web-workers", "parser-diagnostics.jsonl");
      try {
        await appendDiagnosticLine(file, {
          version: 1, at: new Date().toISOString(), type: "parser-rejection",
          ...(input.runId ? { runId: input.runId } : {}), ...(input.projectId ? { projectId: input.projectId } : {}),
          stage: input.stage, sessionId: input.sessionId, generation: input.generation,
          ...(input.resultContract ? { resultContract: input.resultContract } : {}), conversationRefPresent: Boolean(input.conversationRef),
          category, phase,
          ...(input.correctionAttempt === undefined ? {} : { correctionAttempt: input.correctionAttempt }),
          ...(input.correctionBudgetUsed === undefined ? {} : { correctionBudgetUsed: input.correctionBudgetUsed }),
          ...(input.correctionBudgetLimit === undefined ? {} : { correctionBudgetLimit: input.correctionBudgetLimit }),
          ...(input.diagnostic ?? {}),
        });
      } catch { /* diagnostics never affect execution */ }
    },
    async recordOperationDiagnostic(input) {
      if (!config.lifecycleRoot) return;
      const file = resolve(config.lifecycleRoot, "web-workers", "operation-diagnostics.jsonl");
      try { await appendDiagnosticLine(file, { version: 1, at: new Date().toISOString(), type: "browser-operation", ...input }); } catch { /* diagnostics never affect execution */ }
    },
    async dispose() { await backend.dispose(); },
  };
}
