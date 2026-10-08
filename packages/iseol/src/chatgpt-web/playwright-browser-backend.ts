import { chromium, type Browser, type BrowserContext, type Page } from "playwright-core";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import type { PlaywrightBrowserDriverConfig } from "./playwright-browser-config.js";
import { withDurableFileStateLock } from "../services/file-state-lock.js";

export interface PlaywrightBrowserBackend {
  navigate(url: string): Promise<void>;
  currentUrl(): Promise<string>;
  composerCount(): Promise<number>;
  authenticationRequiredCount(): Promise<number>;
  temporaryRestrictionCount(): Promise<number>;
  conversationLimitCount?(): Promise<number>;
  usageLimitCount?(): Promise<number>;
  dismissTemporaryRestriction?(): Promise<boolean>;
  fillComposer(value: string): Promise<void>;
  sendPrompt(): Promise<void>;
  assistantMessageCount(): Promise<number>;
  latestAssistantText(): Promise<string | null>;
  latestAssistantDomText?(): Promise<string | null>;
  latestAssistantRawText(): Promise<string | null>;
  generationControlCount(): Promise<number>;
  closeOwnedPage(): Promise<void>;
  dispose(): Promise<void>;
}

type BackendDeps = {
  launchPersistentContext?: (
    profileRoot: string,
    options: { executablePath?: string; headless: boolean },
  ) => Promise<BrowserContext>;
};

const COMPOSER_SELECTOR = 'textarea:visible, [contenteditable="true"][role="textbox"]:visible, [contenteditable="true"][data-lexical-editor="true"]:visible';
const AUTH_SELECTOR = 'a[href*="/auth/login"], a[href*="/auth/signup"], a[href*="/auth/sign-up"]';
const TEMPORARY_RESTRICTION_TEXT = /(?:too many requests|sending requests too quickly|access (?:has been )?temporarily limited|요청이 너무 많습니다|요청을 너무 빠르게 보내고 있습니다|액세스가 일시적으로 제한)/i;
const CONVERSATION_LIMIT_TEXT = /(?:maximum length for this conversation|reached.{0,20}(?:maximum length|limit).{0,20}(?:for )?this conversation|this conversation.{0,30}(?:has )?reached.{0,20}(?:maximum length|limit)|conversation.{0,30}(?:maximum length|limit).{0,20}reached|이 대화.{0,30}(?:최대 길이|한도).{0,20}(?:도달|초과))/i;
const USAGE_LIMIT_TEXT = /(?:you(?:\x27|’)ve reached (?:your )?.{0,40}(?:message|model|usage|plan|gpt-[a-z0-9._-]+)?.{0,20}limit|(?:message|model|usage|plan|gpt-[a-z0-9._-]+).{0,30}limit.{0,20}(?:reached|reset|try again)|(?:메시지|모델|사용|사용량|계정|gpt-[a-z0-9._-]+).{0,20}(?:한도|제한).{0,20}(?:도달|초과))/i;
const TEMPORARY_DISMISS_TEXT = /^(?:알겠습니다|확인|got it|ok|okay)$/i;
const ASSISTANT_SELECTOR = '[data-message-author-role="assistant"], [data-markdown-text-style="assistant-message"]';
const COPY_SELECTOR = 'button[data-testid="copy-turn-action-button"], button[aria-label="메시지 복사"], button[aria-label="Copy"]';
const ASSISTANT_CONTROL_SELECTOR = 'button, [role="button"], [role="toolbar"], [data-testid*="action"], [aria-hidden="true"]';
const COPY_CAPTURE_TIMEOUT_MS = 2_000;
const INSTALL_CLIPBOARD_CAPTURE_SCRIPT = `(() => {
  const clipboard = navigator.clipboard;
  if (!clipboard) throw new Error("clipboard unavailable");
  const state = {
    clipboard,
    writeDescriptor: Object.getOwnPropertyDescriptor(clipboard, "write"),
    writeTextDescriptor: Object.getOwnPropertyDescriptor(clipboard, "writeText"),
    text: undefined,
    items: undefined,
  };
  globalThis.__iseolClipboardCapture = state;
  Object.defineProperty(clipboard, "write", {
    configurable: true,
    value: async (items) => { state.items = items; },
  });
  Object.defineProperty(clipboard, "writeText", {
    configurable: true,
    value: async (value) => { state.text = String(value); },
  });
})()`;

const WAIT_CLIPBOARD_CAPTURE_SCRIPT = `Boolean(
  globalThis.__iseolClipboardCapture
  && (globalThis.__iseolClipboardCapture.text !== undefined
    || globalThis.__iseolClipboardCapture.items !== undefined)
)`;
const READ_CLIPBOARD_CAPTURE_SCRIPT = `(async () => {
  const state = globalThis.__iseolClipboardCapture;
  if (!state) throw new Error("clipboard capture unavailable");
  if (typeof state.text === "string") return state.text;
  for (const item of state.items ?? []) {
    if (!item?.types?.includes?.("text/plain")) continue;
    const blob = await item.getType("text/plain");
    return await blob.text();
  }
  throw new Error("copied response has no text/plain payload");
})()`;
const RESTORE_CLIPBOARD_CAPTURE_SCRIPT = `(() => {
  const state = globalThis.__iseolClipboardCapture;
  if (!state) return;
  const clipboard = state.clipboard;
  if (state.writeDescriptor) Object.defineProperty(clipboard, "write", state.writeDescriptor);
  else delete clipboard.write;
  if (state.writeTextDescriptor) Object.defineProperty(clipboard, "writeText", state.writeTextDescriptor);
  else delete clipboard.writeText;
  delete globalThis.__iseolClipboardCapture;
})()`;

const GENERATING_SELECTOR = 'button[data-testid="stop-button"], button[aria-label="Stop generating"], button[aria-label="Stop"]';

export type AssistantTextReadCallPoint =
  | "assistant-locator-count"
  | "latest-assistant-locator-count"
  | "latest-assistant-text-evaluate";

export type AssistantTextReadDiagnostic = {
  callPoint: AssistantTextReadCallPoint;
  retryable: boolean;
};

const assistantTextReadDiagnostics = new WeakMap<object, AssistantTextReadDiagnostic>();

export function getAssistantTextReadDiagnostic(error: unknown): AssistantTextReadDiagnostic | undefined {
  return error && typeof error === "object" ? assistantTextReadDiagnostics.get(error) : undefined;
}

function annotateAssistantTextReadFailure(error: unknown, callPoint: AssistantTextReadCallPoint, retryable: boolean): void {
  if (error && typeof error === "object") assistantTextReadDiagnostics.set(error, { callPoint, retryable });
}

function isTransientAssistantDomDetachment(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /(?:element|node).*(?:not attached|detached)|detached from the DOM|stale element/i.test(message);
}

/**
 * Extract only the visible text owned by one assistant message.
 *
 * The caller passes the assistant message element itself, so user turns and
 * earlier assistant messages cannot enter the result. Interactive controls
 * are removed from a detached clone before reading innerText; the original
 * page is never mutated and the response payload is not copied through the
 * OS clipboard.
 */
export function extractAssistantDomText(
  root: Element,
  controlSelector = 'button, [role="button"], [role="toolbar"], [data-testid*="action"], [aria-hidden="true"]',
): string {
  const clone = root.cloneNode(true) as Element;
  clone.querySelectorAll(controlSelector).forEach((node) => node.remove());
  const rendered = (clone as HTMLElement).innerText ?? clone.textContent ?? "";
  return rendered.replaceAll("\u00a0", " ");
}

export async function createPlaywrightBrowserBackend(
  config: Extract<PlaywrightBrowserDriverConfig, { enabled: true }>,
  deps: BackendDeps = {},
): Promise<PlaywrightBrowserBackend> {
  const launchPersistentContext = deps.launchPersistentContext
    ?? ((profileRoot, options) => chromium.launchPersistentContext(profileRoot, options));
  let connectedBrowser: Browser | null = null;
  let ownsContext = true;
  let context: BrowserContext;
  if (config.cdpUrl) {
    connectedBrowser = await chromium.connectOverCDP(config.cdpUrl);
    context = connectedBrowser.contexts()[0] ?? await connectedBrowser.newContext();
    ownsContext = false;
  } else {
    context = await launchPersistentContext(config.profileRoot, {
      ...(config.executablePath ? { executablePath: config.executablePath } : {}),
      headless: config.headless,
    });
  }
  let page: Page | null = await context.newPage();
  let disposed = false;
  const lifecycleFile = config.lifecycleRoot ? resolve(config.lifecycleRoot, "web-workers", "lifecycle.jsonl") : null;
  let lifecycleWrites = Promise.resolve();
  const lifecycle = (type: string, reason?: string) => {
    if (!lifecycleFile) return;
    lifecycleWrites = lifecycleWrites.then(async () => {
      await withDurableFileStateLock(lifecycleFile, async () => {
        await mkdir(dirname(lifecycleFile), { recursive: true });
        let lines: string[] = [];
        try { lines = (await readFile(lifecycleFile, "utf8")).trim().split("\n").filter(Boolean); } catch {}
        lines.push(JSON.stringify({ version: 1, at: new Date().toISOString(), type, ...(reason ? { reason } : {}) }));
        await writeFile(lifecycleFile, `${lines.slice(-1000).join("\n")}\n`, "utf8");
      }, { waitForMs: 2_000 });
    }).catch(() => undefined);
  };
  lifecycle("context-created");
  lifecycle("page-created");
  (context as any).on?.("close", () => lifecycle("context-closed"));
  (page as any).on?.("close", () => lifecycle("page-closed"));
  (page as any).on?.("crash", () => lifecycle("page-crashed"));

  async function ownedPage(): Promise<Page> {
    if (disposed) throw new Error("ChatGPT browser backend is disposed");
    if (!page || page.isClosed()) { page = await context.newPage(); lifecycle("page-created"); }
    return page;
  }

  return {
    async navigate(url) { await (await ownedPage()).goto(url, { waitUntil: "domcontentloaded" }); },
    async currentUrl() { return (await ownedPage()).url(); },
    async composerCount() { return (await ownedPage()).locator(COMPOSER_SELECTOR).count(); },
    async authenticationRequiredCount() { return (await ownedPage()).locator(AUTH_SELECTOR).count(); },
    async temporaryRestrictionCount() {
      const text = await (await ownedPage()).locator("body").innerText();
      return TEMPORARY_RESTRICTION_TEXT.test(text) ? 1 : 0;
    },
    async conversationLimitCount() {
      const text = await (await ownedPage()).locator("body").innerText();
      return CONVERSATION_LIMIT_TEXT.test(text) ? 1 : 0;
    },
    async usageLimitCount() {
      const text = await (await ownedPage()).locator("body").innerText();
      return CONVERSATION_LIMIT_TEXT.test(text) ? 0 : (USAGE_LIMIT_TEXT.test(text) ? 1 : 0);
    },
    async dismissTemporaryRestriction() {
      const button = (await ownedPage()).getByRole("button", { name: TEMPORARY_DISMISS_TEXT });
      if (await button.count() !== 1) return false;
      await button.click();
      return true;
    },
    async fillComposer(value) {
      const composer = (await ownedPage()).locator(COMPOSER_SELECTOR);
      if (await composer.count() !== 1) throw new Error("composer unavailable");
      await composer.fill(value);
    },
    async sendPrompt() {
      const owned = await ownedPage();
      const primary = owned.locator('button[data-testid="send-button"]');
      const primaryCount = await primary.count();
      if (primaryCount > 1) throw new Error("send control ambiguous");
      if (primaryCount === 1) { await primary.click(); return; }
      const semantic = owned.locator(
        'button[aria-label="Send prompt"], button[aria-label="Send message"], button[aria-label="Send"], button[aria-label="보내기"], button[aria-label="전송"]'
      );
      if (await semantic.count() !== 1) throw new Error("send control unavailable or ambiguous");
      await semantic.click();
    },
    async assistantMessageCount() { return (await ownedPage()).locator(ASSISTANT_SELECTOR).count(); },
    async latestAssistantText() {
      const assistant = (await ownedPage()).locator(ASSISTANT_SELECTOR);
      let count: number;
      try {
        count = await assistant.count();
      } catch (error) {
        const retryable = isTransientAssistantDomDetachment(error);
        annotateAssistantTextReadFailure(error, "assistant-locator-count", retryable);
        if (retryable) return null;
        throw error;
      }
      if (count === 0) return null;
      const latest = assistant.last();
      let latestCount: number;
      try {
        latestCount = await latest.count();
      } catch (error) {
        const retryable = isTransientAssistantDomDetachment(error);
        annotateAssistantTextReadFailure(error, "latest-assistant-locator-count", retryable);
        if (retryable) return null;
        throw error;
      }
      if (latestCount === 0) return null;
      if (latestCount !== 1) throw new Error("assistant message DOM scope unavailable or ambiguous");
      let text: string;
      try {
        text = await latest.evaluate(extractAssistantDomText, ASSISTANT_CONTROL_SELECTOR);
      } catch (error) {
        if (isTransientAssistantDomDetachment(error)) return null;
        annotateAssistantTextReadFailure(error, "latest-assistant-text-evaluate", false);
        throw error;
      }
      return typeof text === "string" && text.trim() ? text : null;
    },
    async latestAssistantDomText() {
      const assistant = (await ownedPage()).locator(ASSISTANT_SELECTOR);
      let count: number;
      try {
        count = await assistant.count();
      } catch (error) {
        const retryable = isTransientAssistantDomDetachment(error);
        annotateAssistantTextReadFailure(error, "assistant-locator-count", retryable);
        if (retryable) return null;
        throw error;
      }
      if (count === 0) return null;
      const latest = assistant.last();
      let latestCount: number;
      try {
        latestCount = await latest.count();
      } catch (error) {
        const retryable = isTransientAssistantDomDetachment(error);
        annotateAssistantTextReadFailure(error, "latest-assistant-locator-count", retryable);
        if (retryable) return null;
        throw error;
      }
      if (latestCount === 0) return null;
      if (latestCount !== 1) throw new Error("assistant message DOM scope unavailable or ambiguous");
      let text: string;
      try {
        text = await latest.evaluate(extractAssistantDomText, ASSISTANT_CONTROL_SELECTOR);
      } catch (error) {
        if (isTransientAssistantDomDetachment(error)) return null;
        annotateAssistantTextReadFailure(error, "latest-assistant-text-evaluate", false);
        throw error;
      }
      return typeof text === "string" && text.trim() ? text : null;
    },
    async latestAssistantRawText() {
      const owned = await ownedPage();
      const assistant = owned.locator(ASSISTANT_SELECTOR);
      if (await assistant.count() === 0) return null;
      const turn = assistant.last().locator('xpath=ancestor::*[.//button[@data-testid="copy-turn-action-button" or @aria-label="메시지 복사" or @aria-label="Copy"]][1]');
      if (await turn.count() !== 1) throw new Error("assistant turn copy control unavailable or ambiguous");
      const copy = turn.locator(COPY_SELECTOR);
      if (await copy.count() !== 1) throw new Error("assistant copy control unavailable or ambiguous");
      await owned.evaluate(INSTALL_CLIPBOARD_CAPTURE_SCRIPT);
      let primaryError: unknown;
      try {
        await copy.dispatchEvent("click");
        try {
          await owned.waitForFunction(WAIT_CLIPBOARD_CAPTURE_SCRIPT, undefined, { timeout: COPY_CAPTURE_TIMEOUT_MS });
        } catch {
          throw new Error("ChatGPT clipboard capture failed");
        }
        return await owned.evaluate(READ_CLIPBOARD_CAPTURE_SCRIPT);
      } catch (error) {
        primaryError = error;
        throw error;
      } finally {
        try {
          await owned.evaluate(RESTORE_CLIPBOARD_CAPTURE_SCRIPT);
        } catch {
          if (primaryError === undefined) throw new Error("ChatGPT clipboard capture cleanup failed");
        }
      }
    },
    async generationControlCount() { return (await ownedPage()).locator(GENERATING_SELECTOR).count(); },
    async closeOwnedPage() {
      if (disposed || !page || page.isClosed()) return;
      await page.close();
      lifecycle("page-closed", "owned-page-release");
      page = null;
    },
    async dispose() {
      if (disposed) return;
      disposed = true;
      page = null;
      if (ownsContext) await context.close();
      else (connectedBrowser as (Browser & { disconnect?: () => void }) | null)?.disconnect?.();
      lifecycle("context-disposed");
      await lifecycleWrites;
    },
  };
}
