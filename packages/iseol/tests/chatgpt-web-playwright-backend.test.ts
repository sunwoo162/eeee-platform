import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright-core";
import { createPlaywrightBrowserBackend, extractAssistantDomText, getAssistantTextReadDiagnostic } from "../src/chatgpt-web/playwright-browser-backend.js";
import { parsePatchFrameV1 } from "../src/chatgpt-web/playwright-browser-driver.js";

const config = { enabled: true as const, profileRoot: "C:\\temp\\chatgpt-profile", headless: true };

test("backend rejects a non-loopback CDP endpoint before attempting a connection", async () => {
  const originalConnectOverCDP = chromium.connectOverCDP;
  let connectAttempts = 0;
  chromium.connectOverCDP = async () => {
    connectAttempts += 1;
    throw new Error("network connection must not be attempted");
  };
  try {
    await assert.rejects(
      () => createPlaywrightBrowserBackend({ ...config, cdpUrl: "http://example.com:9222" }),
      /CDP.*loopback/i,
    );
    assert.equal(connectAttempts, 0);
  } finally {
    chromium.connectOverCDP = originalConnectOverCDP;
  }
});

test("assistant DOM extraction removes controls while preserving rendered response text", () => {
  const removed: string[] = [];
  const clone = {
    querySelectorAll(selector: string) {
      assert.match(selector, /button/);
      return [{ remove() { removed.push("copy"); } }, { remove() { removed.push("toolbar"); } }];
    },
    innerText: '{"message":"한국어 \\\"인용\\\" \\\\ 경로","code":"{\\\"ok\\\":true}"}',
    textContent: "unused",
  };
  const root = { cloneNode() { return clone; } };

  assert.equal(extractAssistantDomText(root as any), clone.innerText);
  assert.deepEqual(removed, ["copy", "toolbar"]);
});

test("assistant DOM extractor is self-contained when Playwright serializes it", () => {
  const serialized = new Function(`return (${extractAssistantDomText.toString()})`)() as (root: Element, selector?: string) => string;
  const root = {
    cloneNode() {
      return {
        querySelectorAll(selector: string) {
          assert.match(selector, /button/);
          return [];
        },
        innerText: '{"ok":true}',
        textContent: "unused",
      };
    },
  };

  assert.equal(serialized(root as any), '{"ok":true}');
});

test("backend reads the latest assistant message through scoped DOM extraction without copy", async () => {
  const raw = '{"version":1,"text":"한국어"}';
  const copy = { async count() { throw new Error("copy control must not be queried"); } };
  const turn = { async count() { return 1; }, locator() { return copy; } };
  const root = { cloneNode() { return { querySelectorAll() { return []; }, innerText: raw, textContent: raw }; } };
  const latest = {
    async count() { return 1; },
    evaluate(fn: (element: Element) => string) { return Promise.resolve(fn(root as any)); },
    locator() { return turn; },
  };
  const assistant = { async count() { return 2; }, last() { return latest; } };
  const page = {
    locator(selector: string) { assert.equal(selector, '[data-message-author-role="assistant"]'); return assistant; },
    isClosed() { return false; }, async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });

  assert.equal(await (backend as any).latestAssistantDomText(), raw);
  await backend.dispose();
});

test("backend treats an assistant message detached between count and text lookup as a transient empty read", async () => {
  let assistantCountCalls = 0;
  const latest = {
    async count() {
      assistantCountCalls += 1;
      return assistantCountCalls === 1 ? 0 : 1;
    },
    async evaluate() {
      throw new Error("should not evaluate a detached assistant");
    },
  };
  const assistant = {
    async count() { return 1; },
    last() { return latest; },
  };
  const page = {
    locator(selector: string) {
      assert.equal(selector, '[data-message-author-role="assistant"]');
      return assistant;
    },
    isClosed() { return false; },
    async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });

  assert.equal(await (backend as any).latestAssistantText(), null);
  await backend.dispose();
});

test("backend retries a transient assistant DOM detachment during text evaluation", async () => {
  const latest = {
    async count() { return 1; },
    async evaluate() { throw new Error("Element is not attached to the DOM"); },
  };
  const assistant = {
    async count() { return 1; },
    last() { return latest; },
  };
  const page = {
    locator(selector: string) {
      assert.equal(selector, '[data-message-author-role="assistant"]');
      return assistant;
    },
    isClosed() { return false; },
    async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });

  assert.equal(await (backend as any).latestAssistantText(), null);
  await backend.dispose();
});

test("backend treats transient locator-count detachment as a bounded empty read", async () => {
  const latest = {
    async count() { throw new Error("Element is detached from the DOM"); },
    async evaluate() { throw new Error("should not evaluate a detached assistant"); },
  };
  const assistant = {
    async count() { return 1; },
    last() { return latest; },
  };
  const page = {
    locator() { return assistant; },
    isClosed() { return false; },
    async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });

  assert.equal(await (backend as any).latestAssistantText(), null);
  await backend.dispose();
});

test("backend does not hide non-detachment assistant DOM errors", async () => {
  const latest = {
    async count() { return 1; },
    async evaluate() { throw new Error("assistant selector contract changed"); },
  };
  const assistant = {
    async count() { return 1; },
    last() { return latest; },
  };
  const page = {
    locator() { return assistant; },
    isClosed() { return false; },
    async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });

  await assert.rejects(() => (backend as any).latestAssistantText(), /selector contract changed/);
  await backend.dispose();
});

test("backend records a bounded call point for non-detachment assistant DOM errors", async () => {
  const latest = {
    async count() { return 1; },
    async evaluate() { throw new Error("locator selector secret response text"); },
  };
  const assistant = {
    async count() { return 1; },
    last() { return latest; },
  };
  const page = {
    locator() { return assistant; },
    isClosed() { return false; },
    async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });

  let caught: unknown;
  try { await (backend as any).latestAssistantText(); } catch (error) { caught = error; }
  assert.ok(caught instanceof Error);
  assert.deepEqual(getAssistantTextReadDiagnostic(caught), {
    callPoint: "latest-assistant-text-evaluate",
    retryable: false,
  });
  assert.equal((caught as Error).message, "locator selector secret response text");
  await backend.dispose();
});

test("backend recreates its owned page after conversation close and disposes the persistent context", async () => {
  let pageCount = 0;
  let contextCloseCount = 0;
  const pages: Array<{ closed: boolean; urls: string[] }> = [];

  const context = {
    async newPage() {
      pageCount += 1;
      const state = { closed: false, urls: [] as string[] };
      pages.push(state);
      return {
        async goto(url: string) { if (state.closed) throw new Error("page closed"); state.urls.push(url); },
        url() { return state.urls.at(-1) ?? "about:blank"; },
        locator() { throw new Error("locator not used by lifecycle test"); },
        isClosed() { return state.closed; },
        async close() { state.closed = true; },
      };
    },
    async close() { contextCloseCount += 1; },
  };

  const backend = await (createPlaywrightBrowserBackend as any)(config, {
    launchPersistentContext: async () => context,
  });

  await backend.navigate("https://chatgpt.com/");
  assert.equal(pageCount, 1);
  await backend.closeOwnedPage();
  assert.equal(pages[0]?.closed, true);

  await backend.navigate("https://chatgpt.com/c/conv-2");
  assert.equal(pageCount, 2, "next conversation must get a fresh owned page");
  assert.deepEqual(pages[1]?.urls, ["https://chatgpt.com/c/conv-2"]);

  await backend.dispose();
  assert.equal(contextCloseCount, 1);
  await assert.rejects(() => backend.navigate("https://chatgpt.com/"), /disposed/i);
});

test("composer operations ignore hidden fallback editors", async () => {
  let filled = "";
  const context = {
    async newPage() {
      return {
        async goto() {},
        url() { return "https://chatgpt.com/"; },
        locator(selector: string) {
          const composerSelector = selector.includes("textarea");
          return {
            async count() { return composerSelector ? (selector.includes(":visible") ? 1 : 2) : 0; },
            async fill(value: string) { filled = value; },
          };
        },
        isClosed() { return false; },
        async close() {},
      };
    },
    async close() {},
  };
  const backend = await (createPlaywrightBrowserBackend as any)(config, {
    launchPersistentContext: async () => context,
  });
  assert.equal(await backend.composerCount(), 1);
  await backend.fillComposer("hello");
  assert.equal(filled, "hello");
  await backend.dispose();
});


test("backend captures the latest assistant source through its turn copy action", async () => {
  const raw = "+assert.match(html, new RegExp(`data-action=\"${action}\"`));";
  let clicks = 0;
  let evaluations = 0;
  const copy = { async count() { return 1; }, async dispatchEvent(type: string) { assert.equal(type, "click"); clicks += 1; } };
  const turn = {
    async count() { return 1; },
    locator(selector: string) { assert.equal(selector, 'button[data-testid="copy-turn-action-button"]'); return copy; },
  };
  const assistant = {
    async count() { return 1; }, last() { return this; },
    locator(selector: string) { assert.match(selector, /copy-turn-action-button/); return turn; },
  };
  const page = {
    locator(selector: string) { assert.equal(selector, '[data-message-author-role="assistant"]'); return assistant; },
    async evaluate(expression: unknown) { assert.equal(typeof expression, "string"); evaluations += 1; return evaluations === 2 ? raw : undefined; },
    async waitForFunction(expression: unknown) { assert.equal(typeof expression, "string"); },
    isClosed() { return false; }, async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });
  assert.equal(await (backend as any).latestAssistantRawText(), raw);
  assert.equal(clicks, 1);
  await backend.dispose();
});

test("backend converts clipboard capture failures to a safe bounded error", async () => {
  const secret = "ISEOL_BROWSER_SECRET_SENTINEL";
  const copy = { async count() { return 1; }, async dispatchEvent() {} };
  const turn = { async count() { return 1; }, locator() { return copy; } };
  const assistant = { async count() { return 1; }, last() { return this; }, locator() { return turn; } };
  const page = {
    locator() { return assistant; },
    async evaluate() {},
    async waitForFunction() { throw new Error(secret); },
    isClosed() { return false; }, async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });
  await assert.rejects(
    () => (backend as any).latestAssistantRawText(),
    (error: unknown) => error instanceof Error
      && error.message === "ChatGPT clipboard capture failed"
      && !error.message.includes(secret),
  );
  await backend.dispose();
});

test("backend preserves the primary clipboard failure when capture cleanup also fails", async () => {
  const primarySecret = "ISEOL_CLIPBOARD_PRIMARY_SECRET";
  const cleanupSecret = "ISEOL_CLIPBOARD_CLEANUP_SECRET";
  const copy = { async count() { return 1; }, async dispatchEvent() {} };
  const turn = { async count() { return 1; }, locator() { return copy; } };
  const assistant = { async count() { return 1; }, last() { return this; }, locator() { return turn; } };
  const page = {
    locator() { return assistant; },
    async evaluate(expression: unknown) {
      if (String(expression).includes("delete globalThis.__iseolClipboardCapture")) throw new Error(cleanupSecret);
      if (String(expression).includes("__iseolClipboardCapture")) return undefined;
      throw new Error(primarySecret);
    },
    async waitForFunction() { throw new Error(primarySecret); },
    isClosed() { return false; }, async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });
  await assert.rejects(
    () => (backend as any).latestAssistantRawText(),
    (error: unknown) => error instanceof Error
      && error.message === "ChatGPT clipboard capture failed"
      && !error.message.includes(primarySecret)
      && !error.message.includes(cleanupSecret),
  );
  await backend.dispose();
});


test("PATCH_FRAME_V1 unwraps a diff fence without losing prefixes", () => {
  const frame = [
    "ISEOL_PATCH_V1",
    "```diff",
    "--- /dev/null",
    "+++ b/mirror-state.js",
    "@@ -0,0 +1,3 @@",
    "+export function captureLiveSnapshot(value) {",
    "+  return String(value);",
    "+}",
    "```",
  ].join("\n");

  assert.equal(
    parsePatchFrameV1(frame),
    [
      "--- /dev/null",
      "+++ b/mirror-state.js",
      "@@ -0,0 +1,3 @@",
      "+export function captureLiveSnapshot(value) {",
      "+  return String(value);",
      "+}",
      "",
    ].join("\n"),
  );
});

test("PATCH_FRAME_V1 keeps raw diff backward compatible", () => {
  const raw = [
    "--- a/app.js",
    "+++ b/app.js",
    "@@ -1 +1 @@",
    "-old",
    "+new",
    "",
  ].join("\n");

  assert.equal(
    parsePatchFrameV1(`ISEOL_PATCH_V1\n${raw}`),
    raw,
  );
});

test("PATCH_FRAME_V1 rejects malformed diff fences", () => {
  assert.throws(
    () => parsePatchFrameV1([
      "ISEOL_PATCH_V1",
      "```diff",
      "--- a/app.js",
      "+++ b/app.js",
      "@@ -1 +1 @@",
      "-old",
      "+new",
    ].join("\n")),
    /fence is malformed/i,
  );
});

test("backend detects the visible ChatGPT temporary request-limit message", async () => {
  const page = {
    locator(selector: string) {
      assert.equal(selector, "body");
      return {
        async innerText() {
          return "요청이 너무 많습니다\n요청을 너무 빠르게 보내고 있습니다. 데이터를 보호하기 위해 대화에 대한 액세스가 일시적으로 제한되었습니다.\n몇 분 후 다시 시도해 주세요.";
        },
      };
    },
    isClosed() { return false; },
    async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, {
    launchPersistentContext: async () => context,
  });
  assert.equal(await (backend as any).temporaryRestrictionCount(), 1);
  await backend.dispose();
});

test("backend distinguishes conversation exhaustion from account usage limits", async () => {
  let bodyText = "You've reached the maximum length for this conversation. Start a new chat to continue.";
  const page = {
    locator(selector: string) { assert.equal(selector, "body"); return { async innerText() { return bodyText; } }; },
    isClosed() { return false; }, async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });
  assert.equal(await (backend as any).conversationLimitCount(), 1);
  assert.equal(await (backend as any).usageLimitCount(), 0);
  bodyText = "You've reached your GPT-5 message limit. Try again later.";
  assert.equal(await (backend as any).conversationLimitCount(), 0);
  assert.equal(await (backend as any).usageLimitCount(), 1);
  await backend.dispose();
});

test("backend dismisses the temporary request-limit popup", async () => {
  let clicks = 0;
  const page = {
    locator(selector: string) { assert.equal(selector, "body"); return { async innerText() { return "요청이 너무 많습니다\n몇 분 후 다시 시도해 주세요."; } }; },
    getByRole(role: string, options: { name: RegExp }) {
      assert.equal(role, "button"); assert.match("알겠습니다", options.name);
      return { async count() { return 1; }, async click() { clicks += 1; } };
    },
    isClosed() { return false; }, async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });
  assert.equal(await (backend as any).dismissTemporaryRestriction(), true);
  assert.equal(clicks, 1);
  await backend.dispose();
});

test("backend treats model quota messages as usage limits rather than conversation exhaustion", async () => {
  let bodyText = "You've reached the GPT-5 limit. Please try again later.";
  const page = {
    locator(selector: string) { assert.equal(selector, "body"); return { async innerText() { return bodyText; } }; },
    isClosed() { return false; }, async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });
  assert.equal(await (backend as any).usageLimitCount(), 1);
  bodyText = "GPT-5 사용 한도에 도달했습니다. 나중에 다시 시도해 주세요.";
  assert.equal(await (backend as any).usageLimitCount(), 1);
  assert.equal(await (backend as any).conversationLimitCount(), 0);
  await backend.dispose();
});

test("backend recognizes reached-the-limit-for-this-conversation wording", async () => {
  const page = {
    locator(selector: string) { assert.equal(selector, "body"); return { async innerText() { return "You've reached the limit for this conversation. Start a new chat to continue."; } }; },
    isClosed() { return false; }, async close() {},
  };
  const context = { async newPage() { return page; }, async close() {} };
  const backend = await (createPlaywrightBrowserBackend as any)(config, { launchPersistentContext: async () => context });
  assert.equal(await (backend as any).conversationLimitCount(), 1);
  assert.equal(await (backend as any).usageLimitCount(), 0);
  await backend.dispose();
});
