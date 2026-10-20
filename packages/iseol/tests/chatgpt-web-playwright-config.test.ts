import assert from "node:assert/strict";
import test from "node:test";
import { resolve } from "node:path";
import { resolvePlaywrightBrowserDriverConfig } from "../src/chatgpt-web/playwright-browser-config.js";

const roots = {
  repositoryRoot: resolve("C:/iseol/repo"),
  modelRoot: resolve("C:/iseol/data/model"),
  runRoot: resolve("C:/iseol/data/runs"),
  webRoot: resolve("C:/iseol/repo/web"),
};

test("playwright browser config is disabled by default", () => {
  assert.deepEqual(resolvePlaywrightBrowserDriverConfig({}, roots), { enabled: false });
});

test("enabled playwright browser requires a dedicated safe profile root", () => {
  assert.throws(() => resolvePlaywrightBrowserDriverConfig({
    ISEOL_CHATGPT_BROWSER_ENABLED: "true",
  }, roots), /profile/i);

  for (const profileRoot of [roots.repositoryRoot, roots.modelRoot, roots.runRoot, roots.webRoot]) {
    assert.throws(() => resolvePlaywrightBrowserDriverConfig({
      ISEOL_CHATGPT_BROWSER_ENABLED: "true",
      ISEOL_CHATGPT_BROWSER_PROFILE_ROOT: profileRoot,
    }, roots), /outside/i);
  }
});
test("playwright browser config uses strict booleans and preserves bounded options", () => {
  assert.throws(() => resolvePlaywrightBrowserDriverConfig({
    ISEOL_CHATGPT_BROWSER_ENABLED: "yes",
  }, roots), /true|false/i);

  const profileRoot = resolve("C:/iseol-browser-profile");
  assert.deepEqual(resolvePlaywrightBrowserDriverConfig({
    ISEOL_CHATGPT_BROWSER_ENABLED: "true",
    ISEOL_CHATGPT_BROWSER_PROFILE_ROOT: profileRoot,
    ISEOL_CHATGPT_BROWSER_EXECUTABLE: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    ISEOL_CHATGPT_BROWSER_HEADLESS: "true",
  }, roots), {
    enabled: true,
    profileRoot,
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true,
  });

  assert.throws(() => resolvePlaywrightBrowserDriverConfig({
    ISEOL_CHATGPT_BROWSER_ENABLED: "true",
    ISEOL_CHATGPT_BROWSER_PROFILE_ROOT: profileRoot,
    ISEOL_CHATGPT_BROWSER_HEADLESS: "1",
  }, roots), /true|false/i);
});

test("playwright browser config accepts only loopback CDP endpoints", () => {
  const profileRoot = resolve("C:/iseol-browser-profile");
  const accepted = [
    "http://127.0.0.1:9222",
    "http://localhost:9222",
    "ws://[::1]:9222/devtools/browser/session",
  ];

  for (const cdpUrl of accepted) {
    const config = resolvePlaywrightBrowserDriverConfig({
      ISEOL_CHATGPT_BROWSER_ENABLED: "true",
      ISEOL_CHATGPT_BROWSER_PROFILE_ROOT: profileRoot,
      ISEOL_CHATGPT_BROWSER_CDP_URL: cdpUrl,
    }, roots);
    assert.equal(config.enabled, true);
    if (config.enabled) assert.equal(config.cdpUrl, cdpUrl);
  }

  const rejected = [
    "http://example.com:9222",
    "http://127.0.0.1:9222@attacker.example",
    "http://[::2]:9222",
    "not-a-url",
  ];
  for (const cdpUrl of rejected) {
    assert.throws(() => resolvePlaywrightBrowserDriverConfig({
      ISEOL_CHATGPT_BROWSER_ENABLED: "true",
      ISEOL_CHATGPT_BROWSER_PROFILE_ROOT: profileRoot,
      ISEOL_CHATGPT_BROWSER_CDP_URL: cdpUrl,
    }, roots), /CDP.*loopback/i, cdpUrl);
  }
});
