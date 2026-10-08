/**
 * Loopback bridge used by EEEE's general assistant.
 *
 * EEEE never handles ChatGPT cookies or credentials. This process owns the
 * persistent browser profile and delegates all browser safety/session checks to
 * the existing ISEOL ChatGPT Web adapter.
 */

import { createHash, randomUUID } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { resolve } from "node:path";
import type { WebWorkerSession } from "./contracts.js";
import { resolveChatGptWebBridgeRuntime } from "./browser-service.js";
import type { ChatGptWebBrowserAdapter } from "./browser-adapter.js";
import type { PlaywrightBrowserRoots } from "./playwright-browser-config.js";

type ChatRequest = {
  text?: unknown;
  conversationRef?: unknown;
  runId?: unknown;
};

type BridgeState = {
  adapter: ChatGptWebBrowserAdapter;
  conversationRef?: string;
};

const MAX_BODY_BYTES = 64 * 1024;
const DEFAULT_TIMEOUT_MS = 120_000;

function json(response: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
    "cache-control": "no-store",
  });
  response.end(payload);
}

function readBody(request: IncomingMessage): Promise<string> {
  return new Promise((resolveBody, reject) => {
    let body = "";
    let size = 0;
    request.setEncoding("utf8");
    request.on("data", (chunk: string) => {
      size += Buffer.byteLength(chunk, "utf8");
      if (size > MAX_BODY_BYTES) {
        reject(new Error("request body is too large"));
        request.destroy();
        return;
      }
      body += chunk;
    });
    request.on("end", () => resolveBody(body));
    request.on("error", reject);
  });
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} is required`);
  return value.trim();
}

function optionalRef(value: unknown): string | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  return text(value, "conversationRef");
}

function promptFor(userText: string, runId: string): { body: string; sha256: string } {
  const body = [
    "You are EEEE, the user's persistent personal assistant.",
    "Answer the user's message naturally and helpfully in the user's language.",
    "This is a normal conversation turn. Do not perform external actions.",
    "Return exactly one JSON object and no markdown or prose outside JSON:",
    '{"message":"your complete assistant response"}',
    `User message: ${userText}`,
    `Request id: ${runId}`,
  ].join("\n");
  return { body, sha256: createHash("sha256").update(body, "utf8").digest("hex") };
}

function sessionFor(input: ChatRequest, conversationRef?: string): WebWorkerSession {
  const runId = typeof input.runId === "string" && input.runId.trim() ? input.runId.trim() : `eeee-${randomUUID()}`;
  return {
    version: 1,
    sessionId: `eeee-chat-${randomUUID()}`,
    runId,
    stage: "ANALYZE",
    generation: 1,
    ...(conversationRef ? { conversationRef } : {}),
    policySha256: "eeee-chatgpt-web-assistant-policy",
    status: "ready",
    resultContract: "structured-json",
    createdAt: new Date().toISOString(),
  };
}

async function chat(state: BridgeState, input: ChatRequest): Promise<Record<string, unknown>> {
  const userText = text(input.text, "text");
  const requestedRef = optionalRef(input.conversationRef) ?? state.conversationRef;
  const session = sessionFor(input, requestedRef);
  const prompt = promptFor(userText, session.runId);
  const opened = await state.adapter.openOrResumeSession(session, {
    version: 1, kind: "initial", runId: session.runId, stage: session.stage,
    generation: 1, policySha256: session.policySha256, body: prompt.body, sha256: prompt.sha256,
  });
  const active = { ...session, ...opened };
  const submitted = await state.adapter.submitTurn(active, {
    version: 1, kind: "initial", runId: active.runId, stage: active.stage,
    generation: active.generation, policySha256: active.policySha256, body: prompt.body, sha256: prompt.sha256,
  });
  const withTurn = { ...active, ...(submitted ?? {}) };
  if (!withTurn.conversationRef) throw new Error("ChatGPT Web conversation reference was not created");
  const result = await state.adapter.awaitStructuredResult(
    withTurn, DEFAULT_TIMEOUT_MS, "structured-json",
  );
  if (!result || typeof result !== "object" || Array.isArray(result) || typeof (result as { message?: unknown }).message !== "string") {
    throw new Error("ChatGPT Web returned an invalid assistant response envelope");
  }
  state.conversationRef = withTurn.conversationRef;
  return {
    status: "completed",
    message: (result as { message: string }).message.trim(),
    conversationRef: state.conversationRef,
  };
}

function roots(env: NodeJS.ProcessEnv, cwd: string): PlaywrightBrowserRoots {
  return {
    repositoryRoot: cwd,
    modelRoot: resolve(env.ISEOL_MODEL_ROOT?.trim() || resolve(cwd, "data", "iseol")),
    runRoot: resolve(env.ISEOL_RUN_ROOT?.trim() || resolve(cwd, "data", "runs")),
    webRoot: resolve(cwd, "web"),
    chatGptWebRoot: resolve(env.ISEOL_CHATGPT_WEB_ROOT?.trim() || resolve(cwd, "data", "runs")),
  };
}

export async function startEeeeChatGptWebBridge(options: { host?: string; port?: number } = {}): Promise<{ close(): Promise<void>; port: number }> {
  const cwd = process.cwd();
  const runtime = await resolveChatGptWebBridgeRuntime(process.env, roots(process.env, cwd));
  if (!runtime.config.enabled || !runtime.driver) throw new Error("ChatGPT Web bridge is not configured");
  const state: BridgeState = { adapter: (await import("./production-browser-adapter.js")).createProductionChatGptWebAdapter(runtime.driver) };
  const server = createServer(async (request, response) => {
    try {
      const pathname = new URL(request.url ?? "/", `http://${request.headers.host ?? "127.0.0.1"}`).pathname;
      if (request.method === "GET" && pathname === "/health") return json(response, 200, { status: "ok", service: "chatgpt-web-bridge", connected: Boolean(state.conversationRef) });
      if (request.method !== "POST" || pathname !== "/chat") return json(response, 404, { error: "not found" });
      const input = JSON.parse(await readBody(request)) as ChatRequest;
      return json(response, 200, await chat(state, input));
    } catch (error) {
      const message = error instanceof Error ? error.message : "ChatGPT Web bridge failed";
      return json(response, /auth|login|sign.?in/i.test(message) ? 401 : 503, { status: "blocked", error: message });
    }
  });
  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(options.port ?? 0, options.host ?? "127.0.0.1", () => resolveListen());
  });
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  return {
    port,
    async close() {
      await new Promise<void>((resolveClose, reject) => server.close((error) => error ? reject(error) : resolveClose()));
      await runtime.driver?.dispose?.();
    },
  };
}

if (process.argv[1]?.endsWith("eeee-bridge.js") || process.argv[1]?.endsWith("eeee-bridge.ts")) {
  try {
    const bridge = await startEeeeChatGptWebBridge({
      port: Number.parseInt(process.env.EEEE_CHATGPT_WEB_BRIDGE_PORT ?? "0", 10),
    });
    process.stdout.write(JSON.stringify({ status: "ready", port: bridge.port }) + "\n");
    const shutdown = async () => { await bridge.close(); process.exit(0); };
    process.once("SIGINT", shutdown);
    process.once("SIGTERM", shutdown);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 2;
  }
}
