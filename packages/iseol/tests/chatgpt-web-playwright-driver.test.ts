import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ChatGptWebAuthenticationRequiredError, ChatGptWebSessionLostError, ChatGptWebStructuredResultError } from "../src/chatgpt-web/browser-adapter.js";
import { createPlaywrightChatGptBrowserDriver, parsePatchFrameV1, type PlaywrightBrowserBackend } from "../src/chatgpt-web/playwright-browser-driver.js";

function fakeBackend(overrides: Partial<PlaywrightBrowserBackend> = {}) {
  const urls: string[] = [];
  let currentUrl = "https://chatgpt.com/";
  let closed = 0;
  let sends = 0;
  let filled = "";
  let assistantText: string | null = null;
  let assistantCount = 0;
  let generatingCount = 0;
  const backend: PlaywrightBrowserBackend & Record<string, any> = {
    navigate: async (url) => { urls.push(url); currentUrl = url; },
    currentUrl: async () => currentUrl,
    composerCount: async () => 1,
    authenticationRequiredCount: async () => 0,
    temporaryRestrictionCount: async () => 0,
    conversationLimitCount: async () => 0,
    usageLimitCount: async () => 0,
    fillComposer: async (value: string) => { filled = value; },
    sendPrompt: async () => { sends += 1; },
    assistantMessageCount: async () => assistantCount,
    latestAssistantText: async () => assistantText,
    latestAssistantRawText: async () => assistantText,
    generationControlCount: async () => generatingCount,
    closeOwnedPage: async () => { closed += 1; },
    dispose: async () => undefined,
    ...overrides,
  };
  return { backend, urls, closed: () => closed, sends: () => sends, filled: () => filled, setAssistant: (text: string | null, count = 1) => { assistantText = text; assistantCount = count; }, setGenerating: (count: number) => { generatingCount = count; }, setUrl: (url: string) => { currentUrl = url; } };
}

async function readResponseReadDiagnostics(root: string, ready: (events: Array<Record<string, unknown>>) => boolean): Promise<Array<Record<string, unknown>>> {
  const path = join(root, "web-workers", "response-read-diagnostics.jsonl");
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      const content = await readFile(path, "utf8");
      const events = content.split("\n").filter(Boolean).map((line) => JSON.parse(line) as Record<string, unknown>);
      if (ready(events)) return events;
    } catch {
    }
    await new Promise<void>((resolve) => setTimeout(resolve, 5));
  }
  throw new Error("response-read diagnostics were not persisted");
}

const config = { enabled: true as const, profileRoot: "C:\\temp\\chatgpt-profile", headless: true };

test("PATCH_FRAME_V1 extracts the raw EOF payload without interpreting patch content", () => {
  const patch = [
    "diff --git a/example.ts b/example.ts",
    "--- a/example.ts",
    "+++ b/example.ts",
    "@@ -1 +1 @@",
    "-const oldValue = { items: [\"a,b:c\"] };",
    "+const newValue = { path: \"C:\\\\work\\\\file\", items: [\"a,b:c\"] };",
    " ISEOL_PATCH_V1",
    " trailing prose remains payload",
    "",
  ].join("\n");

  assert.equal(parsePatchFrameV1(`ISEOL_PATCH_V1\n${patch}`), patch);
  assert.equal(parsePatchFrameV1(`ISEOL_PATCH_V1\r\n${patch.replaceAll("\n", "\r\n")}`), patch);
});

test("PATCH_FRAME_V1 rejects missing leading and empty framing", () => {
  for (const input of [
    "diff --git a/a b/a\n",
    "prose\nISEOL_PATCH_V1\ndiff --git a/a b/a\n",
    "ISEOL_PATCH_V1",
    "ISEOL_PATCH_V1\n",
    "ISEOL_PATCH_V1\r\n",
  ]) {
    assert.throws(
      () => parsePatchFrameV1(input),
      (error: unknown) => error instanceof Error && error.name === "ChatGptWebStructuredResultError",
    );
  }
});

test("PATCH_FRAME_V1 failures carry a bounded format diagnostic", () => {
  assert.throws(() => parsePatchFrameV1("prose\nISEOL_PATCH_V1\ndiff"), (error: unknown) => {
    assert.ok(error instanceof ChatGptWebStructuredResultError);
    assert.equal(error.diagnostic?.diagnosticCategory, "patch-frame-format-failure");
    assert.equal(error.diagnostic?.rejectionClass, "frame-missing");
    assert.equal(error.diagnostic?.frameHeaderPresent, false);
    assert.equal(error.diagnostic?.payloadEmpty, false);
    return true;
  });
  assert.throws(() => parsePatchFrameV1("ISEOL_PATCH_V1\n"), (error: unknown) => {
    assert.ok(error instanceof ChatGptWebStructuredResultError);
    assert.equal(error.diagnostic?.diagnosticCategory, "patch-frame-format-failure");
    assert.equal(error.diagnostic?.rejectionClass, "empty-patch");
    assert.equal(error.diagnostic?.frameHeaderPresent, true);
    assert.equal(error.diagnostic?.payloadEmpty, true);
    return true;
  });
});

test("PATCH_FRAME_V1 rejection diagnostics retain only bounded response evidence", () => {
  const sentinel = "ISEOL_BROWSER_SECRET_SENTINEL";
  assert.throws(() => parsePatchFrameV1(`${sentinel}\nISEOL_PATCH_V1`), (error: unknown) => {
    assert.ok(error instanceof ChatGptWebStructuredResultError);
    const diagnostic = error.diagnostic ?? {};
    assert.equal(diagnostic.rejectionClass, "frame-missing");
    assert.equal(diagnostic.responseLengthBucket, "short");
    assert.equal(diagnostic.frameDetected, false);
    assert.equal(diagnostic.diffFenceDetected, false);
    assert.equal(diagnostic.firstLineClass, "secret-or-prose");
    assert.equal(diagnostic.jsonEnvelopeDetected, false);
    assert.equal(diagnostic.unifiedDiffMarkerDetected, false);
    assert.equal(diagnostic.completionSignalPresent, false);
    assert.equal(diagnostic.responsePresent, true);
    assert.match(String(diagnostic.responseSha256), /^[a-f0-9]{64}$/);
    assert.equal(JSON.stringify(diagnostic).includes(sentinel), false);
    return true;
  });
});

test("structured JSON rejection records bounded extraction and parser evidence", async () => {
  let now = 0;
  const malformed = '{"version":1,"summary":"bad",}';
  const expectedHash = createHash("sha256").update(malformed).digest("hex");
  const item = fakeBackend();
  item.setUrl("https://chatgpt.com/c/conv-structured-diagnostic");
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend,
    now: () => now,
    sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-structured-diagnostic", prompt: "payload", promptSha256: "structured-diagnostic" });
  item.setAssistant(malformed, 1);

  await assert.rejects(
    () => driver.readStructuredResult({ conversationRef: "conv-structured-diagnostic", timeoutMs: 2_000, contract: "structured-json" }),
    (error: unknown) => {
      assert.ok(error instanceof ChatGptWebStructuredResultError);
      const diagnostic = error.diagnostic ?? {};
      assert.equal(diagnostic.responsePresent, true);
      assert.equal(diagnostic.completionDetected, true);
      assert.equal(diagnostic.assistantSelection, "latest-after-baseline");
      assert.equal(diagnostic.responseSource, "assistant-copy");
      assert.equal(diagnostic.renderedRawMatch, "yes");
      assert.equal(diagnostic.diagnosticCategory, "response-envelope-malformed");
      assert.equal(diagnostic.rejectionClass, "json-syntax-error");
      assert.equal(diagnostic.parserInputReceived, true);
      assert.equal(diagnostic.parserInputLengthBucket, "short");
      assert.equal(diagnostic.candidateLengthBucket, "short");
      assert.equal(diagnostic.trimChanged, "no");
      assert.equal(diagnostic.codeFenceUnwrapped, "no");
      assert.match(String(diagnostic.responseSha256), /^[a-f0-9]{64}$/);
      assert.equal(diagnostic.responseSha256, expectedHash);
      assert.equal(JSON.stringify(diagnostic).includes(malformed), false);
      return true;
    },
  );
});

test("structured JSON parser diagnostics distinguish fenced candidate transformation", async () => {
  let now = 0;
  const item = fakeBackend();
  item.setUrl("https://chatgpt.com/c/conv-fenced-diagnostic");
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend,
    now: () => now,
    sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-fenced-diagnostic", prompt: "payload", promptSha256: "fenced-diagnostic" });
  item.setAssistant('```json\n[{"version":1}\n```', 1);

  await assert.rejects(
    () => driver.readStructuredResult({ conversationRef: "conv-fenced-diagnostic", timeoutMs: 2_000, contract: "structured-json" }),
    (error: unknown) => {
      assert.ok(error instanceof ChatGptWebStructuredResultError);
      const diagnostic = error.diagnostic ?? {};
      assert.equal(diagnostic.parserInputLengthBucket, "short");
      assert.equal(diagnostic.candidateLengthBucket, "short");
      assert.equal(diagnostic.trimChanged, "no");
      assert.equal(diagnostic.codeFenceUnwrapped, "yes");
      assert.equal(diagnostic.endsWithArrayToken, false);
      return true;
    },
  );
});

test("PATCH_FRAME_V1 rejection diagnostics persist safely and reload as bounded records", async () => {
  const lifecycleRoot = await mkdtemp(join(tmpdir(), "iseol-patch-diagnostics-"));
  const driver = await createPlaywrightChatGptBrowserDriver({ ...config, lifecycleRoot } as any, { backend: fakeBackend().backend });
  const sentinel = "ISEOL_BROWSER_SECRET_SENTINEL";
  await (driver as any).recordParserDiagnostic({
    runId: "run-project-1", projectId: "project-1", stage: "IMPLEMENT", sessionId: "session-1", generation: 2, resultContract: "patch-frame-v1",
    message: "ChatGPT PATCH_FRAME_V1 header is missing or invalid", diagnostic: {
      ...((await import("../src/chatgpt-web/patch-diagnostics.js")).patchRejectionDiagnostic(sentinel, "frame-missing")),
    },
  });
  const file = join(lifecycleRoot, "web-workers", "parser-diagnostics.jsonl");
  const record = JSON.parse((await readFile(file, "utf8")).trim());
  assert.equal(record.resultContract, "patch-frame-v1");
  assert.equal(record.runId, "run-project-1");
  assert.equal(record.projectId, "project-1");
  assert.equal(record.generation, 2);
  assert.equal(record.rejectionClass, "frame-missing");
  assert.equal(record.responseSha256, (await import("node:crypto")).createHash("sha256").update(sentinel).digest("hex"));
  assert.equal(JSON.stringify(record).includes(sentinel), false);
});

test("parser diagnostics persist correction attempt and bounded budget metadata without response text", async () => {
  const lifecycleRoot = await mkdtemp(join(tmpdir(), "iseol-correction-diagnostics-"));
  const driver = await createPlaywrightChatGptBrowserDriver({ ...config, lifecycleRoot } as any, { backend: fakeBackend().backend });
  const sentinel = "ISEOL_RESPONSE_SECRET_SENTINEL";
  await (driver as any).recordParserDiagnostic({
    runId: "run-project-1", projectId: "project-1", stage: "ANALYZE", sessionId: "session-1", generation: 4,
    resultContract: "structured-json", message: "Structured result correction attempt",
    correctionAttempt: 2, correctionBudgetUsed: 2, correctionBudgetLimit: 3,
    diagnostic: { diagnosticCategory: "response-envelope-malformed", rejectionClass: "json-syntax-error", parserInputReceived: true, responseSha256: "a".repeat(64), responseLengthBucket: "medium", sentinelPresent: sentinel.includes("RESPONSE") ? "yes" : "no" },
  });
  const file = join(lifecycleRoot, "web-workers", "parser-diagnostics.jsonl");
  const record = JSON.parse((await readFile(file, "utf8")).trim());
  assert.equal(record.correctionAttempt, 2);
  assert.equal(record.correctionBudgetUsed, 2);
  assert.equal(record.correctionBudgetLimit, 3);
  assert.equal(record.rejectionClass, "json-syntax-error");
  assert.equal(JSON.stringify(record).includes(sentinel), false);
});

test("result reading routes only the explicitly selected stage contract", async () => {
  const patch = [
    "diff --git a/app.js b/app.js",
    "--- a/app.js",
    "+++ b/app.js",
    "@@ -1 +1 @@",
    "-old",
    "+new",
    "",
  ].join("\n");

  const read = async (text: string, contract: "structured-json" | "patch-frame-v1" | "legacy-structured-json") => {
    let now = 0;
    const item = fakeBackend();
    item.setUrl("https://chatgpt.com/c/conv-contract");
    const driver = await createPlaywrightChatGptBrowserDriver(config, {
      backend: item.backend,
      now: () => now,
      sleep: async (ms: number) => { now += ms; },
    } as any);
    await driver.submitPrompt({ conversationRef: "conv-contract", prompt: "payload", promptSha256: `contract-${contract}` });
    item.setAssistant(text, 1);
    return driver.readStructuredResult({ conversationRef: "conv-contract", timeoutMs: 2000, contract } as any);
  };

  assert.equal(await read(`ISEOL_PATCH_V1\n${patch}`, "patch-frame-v1"), patch);
  await assert.rejects(
    () => read('{"version":1}', "patch-frame-v1"),
    (error: unknown) => error instanceof Error && error.name === "ChatGptWebStructuredResultError",
  );

  const legacy = JSON.stringify({
    version: 1,
    intents: [{ intentId: "patch-1", kind: "PROPOSE_PATCH", path: "app.js", patchText: patch }],
  });
  await assert.rejects(
    () => read(legacy, "structured-json"),
    (error: unknown) => error instanceof Error && error.name === "ChatGptWebStructuredResultError",
  );
  assert.equal((await read(legacy, "legacy-structured-json") as any).intents[0].patch, patch);

  await assert.rejects(
    () => read(`ISEOL_PATCH_V1\n${patch}`, "legacy-structured-json"),
    (error: unknown) => error instanceof Error && error.name === "ChatGptWebStructuredResultError",
  );
  await assert.rejects(
    () => read(legacy, "patch-frame-v1"),
    (error: unknown) => error instanceof Error && error.name === "ChatGptWebStructuredResultError",
  );
});

 test("new conversation opens only the canonical root and may remain unassigned before submit", async () => {
  const { backend, urls } = fakeBackend();
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend });
  const opened = await driver.openOrResumeConversation({ prompt: "x", promptSha256: "sha" });
  assert.deepEqual(opened, {});
  assert.deepEqual(urls, ["https://chatgpt.com/"]);
});
test("new conversation waits boundedly for authenticated composer readiness", async () => {
  let now = 0;
  let composerChecks = 0;
  const item = fakeBackend({
    composerCount: async () => {
      composerChecks += 1;
      return composerChecks < 3 ? 0 : 1;
    },
  });
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend,
    now: () => now,
    sleep: async (ms: number) => { now += ms; },
  } as any);
  assert.deepEqual(await driver.openOrResumeConversation({ prompt: "x", promptSha256: "sha" }), {});
  assert.equal(composerChecks, 3);
  assert.ok(now >= 200);
});
test("new conversation waits for ChatGPT to finish redirecting to its canonical conversation", async () => {
  let urlChecks = 0;
  const item = fakeBackend({
    currentUrl: async () => {
      urlChecks += 1;
      return urlChecks === 1 ? "https://chatgpt.com/" : "https://chatgpt.com/c/redirected-conversation";
    },
  });
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend,
    sleep: async () => undefined,
  } as any);

  assert.deepEqual(
    await driver.openOrResumeConversation({ prompt: "x", promptSha256: "sha-redirect" }),
    { conversationRef: "redirected-conversation" },
  );
  assert.ok(urlChecks >= 2, `expected URL stability checks, got ${urlChecks}`);
});
test("resume navigates to and proves the exact requested conversation", async () => {
  const { backend, urls } = fakeBackend();
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend });
  const opened = await driver.openOrResumeConversation({ conversationRef: "conv-2", prompt: "x", promptSha256: "sha" });
  assert.deepEqual(opened, { conversationRef: "conv-2" });
  assert.deepEqual(urls, ["https://chatgpt.com/c/conv-2"]);
});

test("resume rejects a post-navigation conversation identity mismatch", async () => {
  const { backend } = fakeBackend({
    navigate: async () => undefined,
    currentUrl: async () => "https://chatgpt.com/c/other",
  });
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend });
  await assert.rejects(
    () => driver.openOrResumeConversation({ conversationRef: "conv-2", prompt: "x", promptSha256: "sha" }),
    ChatGptWebSessionLostError,
  );
});

test("login URL or login surface requires authentication", async () => {
  const authUrl = fakeBackend({ currentUrl: async () => "https://chatgpt.com/auth/login", composerCount: async () => 0 });
  const authUrlDriver = await createPlaywrightChatGptBrowserDriver(config, { backend: authUrl.backend });
  await assert.rejects(() => authUrlDriver.openOrResumeConversation({ prompt: "x", promptSha256: "sha" }), ChatGptWebAuthenticationRequiredError);

  const authSurface = fakeBackend({ composerCount: async () => 0, authenticationRequiredCount: async () => 2 });
  const authSurfaceDriver = await createPlaywrightChatGptBrowserDriver(config, { backend: authSurface.backend });
  await assert.rejects(() => authSurfaceDriver.openOrResumeConversation({ prompt: "x", promptSha256: "sha" }), ChatGptWebAuthenticationRequiredError);
});
test("guest composer with a login surface still requires authentication", async () => {
  const guest = fakeBackend({ composerCount: async () => 1, authenticationRequiredCount: async () => 2 });
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend: guest.backend });
  await assert.rejects(
    () => driver.openOrResumeConversation({ prompt: "x", promptSha256: "sha" }),
    ChatGptWebAuthenticationRequiredError,
  );
});
test("missing composer waits only for the bounded readiness window while ambiguity fails immediately", async () => {
  for (const count of [0, 2]) {
    let now = 0;
    const item = fakeBackend({ composerCount: async () => count });
    const driver = await createPlaywrightChatGptBrowserDriver(config, {
      backend: item.backend,
      now: () => now,
      sleep: async (ms: number) => { now += ms; },
    } as any);
    await assert.rejects(
      () => driver.openOrResumeConversation({ prompt: "x", promptSha256: "sha" }),
      ChatGptWebSessionLostError,
    );
    if (count === 0) assert.ok(now >= 5_000);
    else assert.equal(now, 0);
  }
});

test("browser failures are bounded session-loss errors and close only the owned page", async () => {
  const broken = fakeBackend({ navigate: async () => { throw new Error("C:/secret/profile detail"); } });
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend: broken.backend });
  await assert.rejects(
    () => driver.openOrResumeConversation({ prompt: "sensitive prompt", promptSha256: "sha" }),
    (error: unknown) => error instanceof ChatGptWebSessionLostError && !error.message.includes("secret") && !error.message.includes("sensitive"),
  );

  const closable = fakeBackend();
  const closeDriver = await createPlaywrightChatGptBrowserDriver(config, { backend: closable.backend });
  await closeDriver.closeConversation("conv-1");
  assert.equal(closable.closed(), 1);
});

test("submit sends one prompt per SHA and captures the first canonical conversation ref", async () => {
  const item = fakeBackend();
  let sendCalls = 0;
  item.backend.sendPrompt = async () => {
    sendCalls += 1;
    item.setUrl("https://chatgpt.com/c/conv-created");
  };
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend: item.backend } as any);
  await driver.openOrResumeConversation({ prompt: "payload", promptSha256: "sha-1" });
  assert.deepEqual(await driver.submitPrompt({ prompt: "payload", promptSha256: "sha-1" }), { conversationRef: "conv-created" });
  assert.deepEqual(await driver.submitPrompt({ conversationRef: "conv-created", prompt: "payload", promptSha256: "sha-1" }), { conversationRef: "conv-created" });
  assert.equal(sendCalls, 1);
  assert.equal(item.filled(), "payload");
});

test("submit revalidates the exact conversation URL before browser mutation", async () => {
  const item = fakeBackend();
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend: item.backend } as any);
  await driver.openOrResumeConversation({ conversationRef: "conv-1", prompt: "payload", promptSha256: "sha-2" });
  item.setUrl("https://chatgpt.com/c/other");
  item.backend.navigate = async () => undefined;
  await assert.rejects(
    () => driver.submitPrompt({ conversationRef: "conv-1", prompt: "payload", promptSha256: "sha-2" }),
    ChatGptWebSessionLostError,
  );
  assert.equal(item.sends(), 0);
  assert.equal(item.filled(), "");
});

test("submit reacquires the requested conversation after a transient SPA identity drift", async () => {
  const item = fakeBackend();
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend: item.backend } as any);
  await driver.openOrResumeConversation({ conversationRef: "conv-1", prompt: "payload", promptSha256: "sha-reacquire" });
  item.setUrl("https://chatgpt.com/c/other");

  assert.deepEqual(
    await driver.submitPrompt({ conversationRef: "conv-1", prompt: "payload", promptSha256: "sha-reacquire" }),
    { conversationRef: "conv-1" },
  );
  assert.equal(item.sends(), 1);
  assert.equal(item.filled(), "payload");
});


test("structured result waits for a stable completed assistant message and parses raw or fenced JSON", async () => {
  let now = 0;
  const item = fakeBackend();
  item.setUrl("https://chatgpt.com/c/conv-1");
  const deps = { backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; } } as any;
  const driver = await createPlaywrightChatGptBrowserDriver(config, deps);
  await driver.submitPrompt({ conversationRef: "conv-1", prompt: "first", promptSha256: "result-sha-1" });
  item.setAssistant('{"version":1}', 1);
  assert.deepEqual(await driver.readStructuredResult({ conversationRef: "conv-1", timeoutMs: 2000, contract: "structured-json" }), { version: 1 });

  now = 0;
  await driver.submitPrompt({ conversationRef: "conv-1", prompt: "second", promptSha256: "result-sha-2" });
  item.setAssistant('```json\n{"version":2}\n```', 2);
  assert.deepEqual(await driver.readStructuredResult({ conversationRef: "conv-1", timeoutMs: 2000, contract: "structured-json" }), { version: 2 });
});

test("structured result does not require the composer after prompt submission", async () => {
  let now = 0;
  let composerChecks = 0;
  const item = fakeBackend({
    composerCount: async () => {
      composerChecks += 1;
      return composerChecks === 1 ? 1 : 0;
    },
  });
  item.setUrl("https://chatgpt.com/c/conv-composer-hydration");
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend,
    now: () => now,
    sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-composer-hydration", prompt: "payload", promptSha256: "composer-hydration-sha" });
  item.setAssistant('{"ready":true}', 1);

  assert.deepEqual(
    await driver.readStructuredResult({ conversationRef: "conv-composer-hydration", timeoutMs: 2_000, contract: "structured-json" }),
    { ready: true },
  );
  assert.equal(composerChecks, 1, "composer is required before submit, not during response polling");
});

test("structured result rejects prose multiple JSON malformed JSON and oversized output", async () => {
  for (const text of [
    'result: {"version":1}',
    '{"version":1} {"version":2}',
    '{bad json}',
    JSON.stringify({ value: "x".repeat(262_145) }),
  ]) {
    let now = 0;
    const item = fakeBackend();
    item.setUrl("https://chatgpt.com/c/conv-1");
    const deps = { backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; } } as any;
    const driver = await createPlaywrightChatGptBrowserDriver(config, deps);
    await driver.submitPrompt({ conversationRef: "conv-1", prompt: "payload", promptSha256: "reject-sha" });
    item.setAssistant(text, 1);
    await assert.rejects(
      () => driver.readStructuredResult({ conversationRef: "conv-1", timeoutMs: 2000, contract: "structured-json" }),
      (error: unknown) => error instanceof Error && error.name === "ChatGptWebStructuredResultError",
    );
  }
});

test("generation must settle for 750ms and timeout is session loss", async () => {
  let now = 0;
  const item = fakeBackend();
  item.setUrl("https://chatgpt.com/c/conv-1");
  const sleep = async (ms: number) => { now += ms; if (now >= 400) item.setGenerating(0); };
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend: item.backend, now: () => now, sleep } as any);
  await driver.submitPrompt({ conversationRef: "conv-1", prompt: "payload", promptSha256: "settle-sha" });
  item.setAssistant('{"ok":true}', 1);
  item.setGenerating(1);
  assert.deepEqual(await driver.readStructuredResult({ conversationRef: "conv-1", timeoutMs: 2000, contract: "structured-json" }), { ok: true });
  assert.ok(now >= 1150);

  let timedNow = 0;
  const timedItem = fakeBackend();
  timedItem.setUrl("https://chatgpt.com/c/conv-1");
  const timed = await createPlaywrightChatGptBrowserDriver(config, {
    backend: timedItem.backend, now: () => timedNow, sleep: async (ms: number) => { timedNow += ms; },
  } as any);
  await timed.submitPrompt({ conversationRef: "conv-1", prompt: "payload", promptSha256: "timeout-sha" });
  timedItem.setAssistant('{"late":true}', 1);
  timedItem.setGenerating(1);
  await assert.rejects(
    () => timed.readStructuredResult({ conversationRef: "conv-1", timeoutMs: 500, contract: "structured-json" }),
    (error: unknown) => error instanceof ChatGptWebSessionLostError
      && error.failureClass === "response-timeout",
  );
});

test("structured result prefers the message-scoped DOM text and preserves JSON characters", async () => {
  let now = 0;
  const payload = {
    version: 1,
    message: '한국어 "인용" \\ 경로',
    nested: { json: "{\\\"ok\\\":true}" },
  };
  const domText = JSON.stringify(payload);
  const item = fakeBackend({
    latestAssistantDomText: async () => domText,
    latestAssistantRawText: async () => { throw new Error("clipboard must not be used for structured JSON"); },
  } as any);
  item.setUrl("https://chatgpt.com/c/conv-dom");
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-dom", prompt: "payload", promptSha256: "dom-sha" });
  item.setAssistant(domText, 1);

  assert.deepEqual(
    await driver.readStructuredResult({ conversationRef: "conv-dom", timeoutMs: 2_000, contract: "structured-json" }),
    payload,
  );
});

test("structured result fails closed when the assistant DOM identity changes during extraction", async () => {
  let now = 0;
  let domRead = false;
  const item = fakeBackend({
    latestAssistantDomText: async () => { domRead = true; return '{"value":1}'; },
    latestAssistantText: async () => domRead ? '{"value":2}' : '{"value":1}',
  } as any);
  item.setUrl("https://chatgpt.com/c/conv-dom-identity");
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-dom-identity", prompt: "payload", promptSha256: "dom-identity-sha" });
  item.setAssistant('{"value":1}', 1);

  await assert.rejects(
    () => driver.readStructuredResult({ conversationRef: "conv-dom-identity", timeoutMs: 2_000, contract: "structured-json" }),
    (error: unknown) => error instanceof ChatGptWebSessionLostError
      && error.failureClass === "conversation-identity-changed",
  );
});

test("structured result records bounded read stages and DOM response source", async () => {
  let now = 0;
  const lifecycleRoot = await mkdtemp(join(tmpdir(), "iseol-response-read-diagnostics-success-"));
  const item = fakeBackend({ latestAssistantDomText: async () => '{"ok":true}' });
  item.setUrl("https://chatgpt.com/c/conv-read-diagnostics");
  const driver = await createPlaywrightChatGptBrowserDriver({ ...config, lifecycleRoot } as any, {
    backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-read-diagnostics", prompt: "payload", promptSha256: "read-diagnostics-sha" });
  item.setAssistant('{"ok":true}', 1);

  assert.deepEqual(
    await driver.readStructuredResult({ requestId: "proposal-read-diagnostics-1", conversationRef: "conv-read-diagnostics", timeoutMs: 2_000, contract: "structured-json" }),
    { ok: true },
  );
  const events = await readResponseReadDiagnostics(lifecycleRoot, (events) => events.some((event) => event.stage === "response-parse" && event.phase === "complete"));
  const stages = new Set(events.map((event) => event.stage));
  for (const stage of ["pending-submission", "conversation-identity", "authentication-state", "assistant-locator", "generation-control", "assistant-text", "assistant-stability", "dom-extraction", "final-identity", "response-parse"]) {
    assert.ok(stages.has(stage), `missing diagnostic stage ${stage}`);
  }
  assert.ok(events.some((event) => event.stage === "dom-extraction" && event.phase === "complete" && event.domExtractionSucceeded === true));
  assert.ok(events.some((event) => event.stage === "dom-extraction" && event.phase === "complete" && event.responseLengthBucket === "short"));
  assert.ok(events.some((event) => event.stage === "dom-extraction" && event.responseSource === "assistant-dom"));
  assert.ok(events.some((event) => event.stage === "response-parse" && event.phase === "complete" && event.responseSource === "assistant-dom"));
  assert.ok(events.every((event) => event.requestId === "proposal-read-diagnostics-1"));
  assert.ok(!JSON.stringify(events).includes('{"ok":true}'));
});

test("structured result records the first locator stage failure without changing its class", async () => {
  let now = 0;
  const lifecycleRoot = await mkdtemp(join(tmpdir(), "iseol-response-read-diagnostics-failure-"));
  const item = fakeBackend({ generationControlCount: async () => { throw new Error("generation locator unavailable"); } });
  item.setUrl("https://chatgpt.com/c/conv-read-diagnostics-failure");
  const driver = await createPlaywrightChatGptBrowserDriver({ ...config, lifecycleRoot } as any, {
    backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-read-diagnostics-failure", prompt: "payload", promptSha256: "read-diagnostics-failure-sha" });
  item.setAssistant('{"ok":true}', 1);

  await assert.rejects(
    () => driver.readStructuredResult({ requestId: "proposal-read-diagnostics-failure-1", conversationRef: "conv-read-diagnostics-failure", timeoutMs: 2_000, contract: "structured-json" }),
    (error: unknown) => error instanceof ChatGptWebSessionLostError && error.failureClass === "locator-missing",
  );
  const events = await readResponseReadDiagnostics(lifecycleRoot, (events) => events.some((event) => event.phase === "failure"));
  const firstFailure = events.find((event) => event.phase === "failure");
  assert.equal(firstFailure?.stage, "generation-control");
  assert.equal(firstFailure?.failureClass, "locator-missing");
  assert.ok(!events.some((event) => event.stage === "response-parse"));
});

test("structured result waits after an empty assistant locator and records when text becomes available", async () => {
  let now = 0;
  let assistantCountCalls = 0;
  const item = fakeBackend({
    assistantMessageCount: async () => {
      assistantCountCalls += 1;
      return assistantCountCalls <= 2 ? 0 : 1;
    },
    generationControlCount: async () => assistantCountCalls <= 2 ? 1 : 0,
    latestAssistantText: async () => '{"ok":true}',
    latestAssistantDomText: async () => '{"ok":true}',
  });
  const lifecycleRoot = await mkdtemp(join(tmpdir(), "iseol-response-read-diagnostics-wait-"));
  item.setUrl("https://chatgpt.com/c/conv-read-wait");
  const driver = await createPlaywrightChatGptBrowserDriver({ ...config, lifecycleRoot } as any, {
    backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-read-wait", prompt: "payload", promptSha256: "read-wait-sha" });

  assert.deepEqual(
    await driver.readStructuredResult({ requestId: "proposal-read-wait-1", conversationRef: "conv-read-wait", timeoutMs: 2_000, contract: "structured-json" }),
    { ok: true },
  );
  const events = await readResponseReadDiagnostics(lifecycleRoot, (events) => events.some((event) => event.stage === "response-parse" && event.phase === "complete"));
  const firstLocator = events.find((event) => event.stage === "assistant-locator" && event.phase === "complete");
  assert.equal(firstLocator?.assistantCount, 0);
  assert.equal(firstLocator?.awaitingAssistant, true);
  const textStart = events.find((event) => event.stage === "assistant-text" && event.phase === "start");
  assert.equal(textStart?.assistantCount, 1);
});

test("structured result retries a transient empty assistant text read within the same deadline", async () => {
  let now = 0;
  let assistantCountCalls = 0;
  let textCalls = 0;
  const item = fakeBackend({
    assistantMessageCount: async () => {
      assistantCountCalls += 1;
      return assistantCountCalls === 1 ? 0 : 1;
    },
    generationControlCount: async () => 0,
    latestAssistantText: async () => {
      textCalls += 1;
      return textCalls === 1 ? null : '{"ok":true}';
    },
    latestAssistantDomText: async () => '{"ok":true}',
  });
  item.setUrl("https://chatgpt.com/c/conv-text-race");
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend,
    now: () => now,
    sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-text-race", prompt: "payload", promptSha256: "text-race-sha" });

  assert.deepEqual(
    await driver.readStructuredResult({ conversationRef: "conv-text-race", timeoutMs: 2_000, contract: "structured-json" }),
    { ok: true },
  );
  assert.ok(textCalls >= 2, `expected a retry after the transient empty read, got ${textCalls} reads`);
});

test("structured result times out without reading assistant text when no assistant appears", async () => {
  let now = 0;
  const lifecycleRoot = await mkdtemp(join(tmpdir(), "iseol-response-read-diagnostics-no-assistant-"));
  const item = fakeBackend({
    assistantMessageCount: async () => 0,
    generationControlCount: async () => 1,
    latestAssistantText: async () => { throw new Error("assistant text must not be read without a new assistant"); },
  });
  item.setUrl("https://chatgpt.com/c/conv-no-assistant");
  const driver = await createPlaywrightChatGptBrowserDriver({ ...config, lifecycleRoot } as any, {
    backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-no-assistant", prompt: "payload", promptSha256: "no-assistant-sha" });

  await assert.rejects(
    () => driver.readStructuredResult({ requestId: "proposal-read-no-assistant-1", conversationRef: "conv-no-assistant", timeoutMs: 500, contract: "structured-json" }),
    (error: unknown) => error instanceof ChatGptWebSessionLostError && error.failureClass === "response-timeout",
  );
  const events = await readResponseReadDiagnostics(lifecycleRoot, (events) => events.some((event) => event.phase === "failure"));
  assert.ok(events.some((event) => event.stage === "assistant-locator" && event.phase === "complete" && event.assistantCount === 0 && event.awaitingAssistant === true));
  assert.ok(!events.some((event) => event.stage === "assistant-text"));
});

test("probe classifies exact ready auth-required and lost states", async () => {
  const item = fakeBackend();
  item.setUrl("https://chatgpt.com/c/conv-1");
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend: item.backend } as any);
  assert.equal(await driver.probeConversation("conv-1"), "ready");

  item.setUrl("https://chatgpt.com/auth/login");
  assert.equal(await driver.probeConversation("conv-1"), "auth-required");

  item.setUrl("https://chatgpt.com/c/other");
  assert.equal(await driver.probeConversation("conv-1"), "lost");
});

test("probe treats a guest composer with login controls as auth-required", async () => {
  const guest = fakeBackend({ authenticationRequiredCount: async () => 2 });
  guest.setUrl("https://chatgpt.com/c/conv-1");
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend: guest.backend } as any);
  assert.equal(await driver.probeConversation("conv-1"), "auth-required");
});

test("the same prompt SHA is deduplicated per conversation rather than globally", async () => {
  const item = fakeBackend();
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend: item.backend } as any);

  item.setUrl("https://chatgpt.com/c/conv-a");
  await driver.submitPrompt({ conversationRef: "conv-a", prompt: "payload", promptSha256: "same-sha" });
  item.setUrl("https://chatgpt.com/c/conv-b");
  await driver.submitPrompt({ conversationRef: "conv-b", prompt: "payload", promptSha256: "same-sha" });

  assert.equal(item.sends(), 2);
});

test("first submit waits boundedly for ChatGPT to assign the canonical conversation URL", async () => {
  let now = 0;
  const item = fakeBackend();
  item.backend.sendPrompt = async () => undefined;
  const sleep = async (ms: number) => {
    now += ms;
    if (now >= 6_000) item.setUrl("https://chatgpt.com/c/conv-delayed");
  };
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend, now: () => now, sleep,
  } as any);

  assert.deepEqual(
    await driver.submitPrompt({ prompt: "payload", promptSha256: "delayed-sha" }),
    { conversationRef: "conv-delayed" },
  );
  assert.ok(now >= 6_000);
});

test("result reading ignores assistant messages that existed before the submitted turn", async () => {
  let now = 0;
  const item = fakeBackend();
  item.setUrl("https://chatgpt.com/c/conv-1");
  item.setAssistant('{"old":true}', 1);
  const sleep = async (ms: number) => {
    now += ms;
    if (now >= 900) item.setAssistant('{"new":true}', 2);
  };
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend, now: () => now, sleep,
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-1", prompt: "next", promptSha256: "new-turn" });

  assert.deepEqual(
    await driver.readStructuredResult({ conversationRef: "conv-1", timeoutMs: 2500, contract: "structured-json" }),
    { new: true },
  );
  assert.ok(now >= 1650);
});

test("result reading fails closed when this driver has no pending submission baseline", async () => {
  let now = 0;
  const item = fakeBackend();
  item.setUrl("https://chatgpt.com/c/conv-1");
  item.setAssistant('{"stale":true}', 1);
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
  } as any);

  await assert.rejects(
    () => driver.readStructuredResult({ conversationRef: "conv-1", timeoutMs: 1000, contract: "structured-json" }),
    (error: unknown) => error instanceof ChatGptWebSessionLostError
      && error.failureClass === "pending-submission-missing",
  );
});

test("result reading preserves bounded identity and extraction failure classes", async () => {
  const identity = fakeBackend();
  identity.setUrl("https://chatgpt.com/c/conv-1");
  const identityDriver = await createPlaywrightChatGptBrowserDriver(config, { backend: identity.backend } as any);
  await identityDriver.submitPrompt({ conversationRef: "conv-1", prompt: "payload", promptSha256: "identity-sha" });
  identity.setUrl("https://chatgpt.com/c/other");
  await assert.rejects(
    () => identityDriver.readStructuredResult({ conversationRef: "conv-1", timeoutMs: 1000, contract: "structured-json" }),
    (error: unknown) => error instanceof ChatGptWebSessionLostError
      && error.failureClass === "conversation-identity-changed",
  );

  let now = 0;
  const extraction = fakeBackend({
    latestAssistantRawText: async () => { throw new Error("assistant turn copy control unavailable or ambiguous"); },
  });
  extraction.setUrl("https://chatgpt.com/c/conv-1");
  const extractionDriver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: extraction.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
  } as any);
  await extractionDriver.submitPrompt({ conversationRef: "conv-1", prompt: "payload", promptSha256: "extraction-sha" });
  extraction.setAssistant('{"ok":true}', 1);
  await assert.rejects(
    () => extractionDriver.readStructuredResult({ conversationRef: "conv-1", timeoutMs: 2000, contract: "structured-json" }),
    (error: unknown) => error instanceof ChatGptWebSessionLostError
      && error.failureClass === "assistant-response-extraction-failed",
  );
});

test("concurrent duplicate submissions share one in-flight browser send", async () => {
  const item = fakeBackend();
  item.setUrl("https://chatgpt.com/c/conv-1");
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend: item.backend } as any);
  const input = { conversationRef: "conv-1", prompt: "payload", promptSha256: "concurrent-sha" };

  const [first, second] = await Promise.all([driver.submitPrompt(input), driver.submitPrompt(input)]);

  assert.equal(item.sends(), 1);
  assert.deepEqual(first, { conversationRef: "conv-1" });
  assert.deepEqual(second, { conversationRef: "conv-1" });
});

test("restart resumes the exact persisted conversation without creating a replacement", async () => {
  const shared = { url: "https://chatgpt.com/", sends: 0 };
  const first = fakeBackend({
    currentUrl: async () => shared.url,
    navigate: async (url) => { shared.url = url; },
    sendPrompt: async () => { shared.sends += 1; shared.url = "https://chatgpt.com/c/conv-persisted"; },
  });
  const driverA = await createPlaywrightChatGptBrowserDriver(config, { backend: first.backend });
  await driverA.openOrResumeConversation({ prompt: "payload", promptSha256: "restart-sha" });
  const submitted = await driverA.submitPrompt({ prompt: "payload", promptSha256: "restart-sha" });
  assert.deepEqual(submitted, { conversationRef: "conv-persisted" });

  const resumeUrls: string[] = [];
  const second = fakeBackend({
    currentUrl: async () => shared.url,
    navigate: async (url) => { resumeUrls.push(url); shared.url = url; },
  });
  const driverB = await createPlaywrightChatGptBrowserDriver(config, { backend: second.backend });
  const resumed = await driverB.openOrResumeConversation({ conversationRef: "conv-persisted", prompt: "payload", promptSha256: "restart-sha" });
  assert.deepEqual(resumed, { conversationRef: "conv-persisted" });
  assert.deepEqual(resumeUrls, ["https://chatgpt.com/c/conv-persisted"]);
  assert.equal(shared.sends, 1);
});

test("first submit ignores provisional WEB conversation refs until canonical identity arrives", async () => {
  let now = 0;
  const item = fakeBackend();
  item.backend.sendPrompt = async () => {
    item.setUrl("https://chatgpt.com/c/local-chatgpt%3Atemporary-ref");
  };
  const sleep = async (ms: number) => {
    now += ms;
    if (now >= 300) item.setUrl("https://chatgpt.com/c/conv-canonical");
  };
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend, now: () => now, sleep,
  } as any);

  assert.deepEqual(
    await driver.submitPrompt({ prompt: "payload", promptSha256: "provisional-sha" }),
    { conversationRef: "conv-canonical" },
  );
  assert.ok(now >= 300);
});


test("closing a conversation clears first-submit dedupe for the next owned conversation", async () => {
  const item = fakeBackend();
  let sequence = 0;
  item.backend.sendPrompt = async () => {
    sequence += 1;
    item.setUrl(`https://chatgpt.com/c/conv-${sequence}`);
  };
  const driver = await createPlaywrightChatGptBrowserDriver(config, { backend: item.backend } as any);

  await driver.openOrResumeConversation({ prompt: "payload", promptSha256: "repeat-sha" });
  assert.deepEqual(
    await driver.submitPrompt({ prompt: "payload", promptSha256: "repeat-sha" }),
    { conversationRef: "conv-1" },
  );
  await driver.closeConversation("conv-1");

  await driver.openOrResumeConversation({ prompt: "payload", promptSha256: "repeat-sha" });
  assert.deepEqual(
    await driver.submitPrompt({ prompt: "payload", promptSha256: "repeat-sha" }),
    { conversationRef: "conv-2" },
  );
  assert.equal(sequence, 2);
});


test("structured result hydrates a raw unified diff patch appendix", async () => {
  let now = 0;
  const item = fakeBackend();
  item.setUrl("https://chatgpt.com/c/conv-patch");
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-patch", prompt: "payload", promptSha256: "patch-sha" });
  const patch = [
    "diff --git a/index.html b/index.html", "--- a/index.html", "+++ b/index.html", "@@ -1 +1 @@",
    "-<meta name=\"old\">", "+<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">",
  ].join("\n") + "\n";
  const header = { version: 1, intents: [{ intentId: "patch-1", kind: "PROPOSE_PATCH", path: "index.html", patch: "@@ISEOL_PATCH:patch-1@@" }] };
  item.setAssistant(`${JSON.stringify(header)}\n@@ISEOL_PATCH_BEGIN:patch-1@@\n${patch.trimEnd()}\n@@ISEOL_PATCH_END:patch-1@@`, 1);
  const result = await driver.readStructuredResult({ conversationRef: "conv-patch", timeoutMs: 2000, contract: "legacy-structured-json" }) as any;
  assert.equal(result.intents[0].patch, patch);
});


test("structured result requires raw appendix transport for PROPOSE_PATCH", async () => {
  for (const patch of ["@@ISEOL_PATCH:patch-1@@", "diff --git a/a b/a\n--- a/a\n+++ b/a\n"]) {
    let now = 0;
    const item = fakeBackend();
    item.setUrl("https://chatgpt.com/c/conv-patch-required");
    const driver = await createPlaywrightChatGptBrowserDriver(config, {
      backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
    } as any);
    await driver.submitPrompt({ conversationRef: "conv-patch-required", prompt: "payload", promptSha256: `required-${patch.length}` });
    item.setAssistant(JSON.stringify({ version: 1, intents: [{ intentId: "patch-1", kind: "PROPOSE_PATCH", path: "a", patch }] }), 1);
    await assert.rejects(
      () => driver.readStructuredResult({ conversationRef: "conv-patch-required", timeoutMs: 2000, contract: "legacy-structured-json" }),
      (error: unknown) => error instanceof Error && error.name === "ChatGptWebStructuredResultError",
    );
  }
});

test("structured result rejects invalid raw unified diff syntax before Desktop dispatch", async () => {
  const invalidPatches = [
    [
      "diff --git a/a.txt b/a.txt", "--- a/a.txt", "+++ b/a.txt", "@@ -1 +1 @@", "-old", "+new",
      "diff --git a/b.txt b/b.txt", "--- a/b.txt", "+++ b/b.txt", "@@ -1 +1 @@", "-old", "+new", "",
    ].join("\n"),
    [
      "diff --git a/app.test.js b/app.test.js", "new file mode 100644", "--- /dev/null", "+++ b/app.test.js",
      "@@ -0,0 +1,3 @@", "+line one", "-line two", "+line three", "",
    ].join("\n"),
    [
      "diff --git a/app.js b/app.js", "--- a/app.js", "+++ b/app.js", "@@ -0,0 +1,3 @@", "+one", "+two", "",
    ].join("\n"),
  ];
  for (const [index, patch] of invalidPatches.entries()) {
    let now = 0;
    const item = fakeBackend();
    item.setUrl("https://chatgpt.com/c/conv-invalid-patch");
    const driver = await createPlaywrightChatGptBrowserDriver(config, {
      backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
    } as any);
    await driver.submitPrompt({ conversationRef: "conv-invalid-patch", prompt: "payload", promptSha256: `invalid-patch-${index}` });
    const header = { version: 1, intents: [{ intentId: "patch-1", kind: "PROPOSE_PATCH", path: "app.test.js", patch: "@@ISEOL_PATCH:patch-1@@" }] };
    item.setAssistant(`${JSON.stringify(header)}\n@@ISEOL_PATCH_BEGIN:patch-1@@\n${patch.trimEnd()}\n@@ISEOL_PATCH_END:patch-1@@`, 1);
    await assert.rejects(
      () => driver.readStructuredResult({ conversationRef: "conv-invalid-patch", timeoutMs: 2000, contract: "legacy-structured-json" }),
      (error: unknown) => error instanceof Error && error.name === "ChatGptWebStructuredResultError",
    );
  }
});


test("structured result canonicalizes unprefixed body lines only for a new-file patch", async () => {
  let now = 0;
  const item = fakeBackend();
  item.setUrl("https://chatgpt.com/c/conv-new-file-patch");
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-new-file-patch", prompt: "payload", promptSha256: "new-file-patch" });
  const patch = [
    "diff --git a/smoke.test.js b/smoke.test.js", "new file mode 100644", "--- /dev/null", "+++ b/smoke.test.js",
    "@@ -0,0 +1,3 @@", "+line one", "", "line two", "+line three",
  ].join("\n");
  const header = { version: 1, intents: [{ intentId: "patch-new", kind: "PROPOSE_PATCH", path: "smoke.test.js", patch: "@@ISEOL_PATCH:patch-new@@" }] };
  item.setAssistant(`${JSON.stringify(header)}\n@@ISEOL_PATCH_BEGIN:patch-new@@\n${patch}\n@@ISEOL_PATCH_END:patch-new@@`, 1);
  const result = await driver.readStructuredResult({ conversationRef: "conv-new-file-patch", timeoutMs: 2000, contract: "legacy-structured-json" }) as any;
  assert.equal(result.intents[0].patch, [
    "diff --git a/smoke.test.js b/smoke.test.js", "new file mode 100644", "--- /dev/null", "+++ b/smoke.test.js",
    "@@ -0,0 +1,4 @@", "+line one", "+", "+line two", "+line three", "",
  ].join("\n"));
});


test("structured result parses lossless copied source when rendered markdown consumes patch syntax", async () => {
  let now = 0;
  const rawPatch = [
    "diff --git a/app.test.js b/app.test.js", "--- a/app.test.js", "+++ b/app.test.js", "@@ -1 +1 @@",
    '-assert.match(html, new RegExp(data-action="${action}"));',
    '+assert.match(html, new RegExp(`data-action="${action}"`));',
  ].join("\n") + "\n";
  const header = { version: 1, intents: [{ intentId: "patch-raw", kind: "PROPOSE_PATCH", path: "app.test.js", patch: "@@ISEOL_PATCH:patch-raw@@" }] };
  const raw = `${JSON.stringify(header)}\n@@ISEOL_PATCH_BEGIN:patch-raw@@\n${rawPatch.trimEnd()}\n@@ISEOL_PATCH_END:patch-raw@@`;
  const rendered = raw.replaceAll("`", "").replace(/^\+/gm, "");
  const item = fakeBackend({ latestAssistantRawText: async () => raw } as any);
  item.setUrl("https://chatgpt.com/c/conv-lossless");
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-lossless", prompt: "payload", promptSha256: "lossless-sha" });
  item.setAssistant(rendered, 1);
  const result = await driver.readStructuredResult({ conversationRef: "conv-lossless", timeoutMs: 2000, contract: "legacy-structured-json" }) as any;
  assert.equal(result.intents[0].patch, rawPatch);
});


test("structured result drops unprefixed blank-line noise inside an existing-file hunk", async () => {
  let now = 0;
  const item = fakeBackend();
  item.setUrl("https://chatgpt.com/c/conv-blank-noise");
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend, now: () => now, sleep: async (ms: number) => { now += ms; },
  } as any);
  await driver.submitPrompt({ conversationRef: "conv-blank-noise", prompt: "payload", promptSha256: "blank-noise" });
  const noisyPatch = [
    "diff --git a/index.html b/index.html", "--- a/index.html", "+++ b/index.html", "@@ -1,2 +1,2 @@",
    "", " <!doctype html>", "", "-<title>Old</title>", "+<title>New</title>",
  ].join("\n");
  const header = { version: 1, intents: [{ intentId: "patch-blank", kind: "PROPOSE_PATCH", path: "index.html", patch: "@@ISEOL_PATCH:patch-blank@@" }] };
  item.setAssistant(`${JSON.stringify(header)}\n@@ISEOL_PATCH_BEGIN:patch-blank@@\n${noisyPatch}\n@@ISEOL_PATCH_END:patch-blank@@`, 1);
  const result = await driver.readStructuredResult({ conversationRef: "conv-blank-noise", timeoutMs: 2000, contract: "legacy-structured-json" }) as any;
  assert.equal(result.intents[0].patch, [
    "diff --git a/index.html b/index.html", "--- a/index.html", "+++ b/index.html", "@@ -1,2 +1,2 @@",
    " <!doctype html>", "-<title>Old</title>", "+<title>New</title>", "",
  ].join("\n"));
});

test("resume tolerates composer hydration beyond five seconds", async () => {
  let now = 0;
  let composerChecks = 0;
  const item = fakeBackend({
    composerCount: async () => {
      composerChecks += 1;
      return now >= 6_000 ? 1 : 0;
    },
  });
  const driver = await createPlaywrightChatGptBrowserDriver(config, {
    backend: item.backend,
    now: () => now,
    sleep: async (ms: number) => { now += ms; },
  } as any);

  assert.deepEqual(
    await driver.openOrResumeConversation({ conversationRef: "conv-slow-hydration", prompt: "x", promptSha256: "sha" }),
    { conversationRef: "conv-slow-hydration" },
  );
  assert.ok(now >= 6_000);
  assert.ok(composerChecks > 50);
});
