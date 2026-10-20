import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../app/static/app.js", import.meta.url), "utf8");

function response(body, ok = true) {
  return { ok, json: async () => body };
}

function createHarness(launchResponse) {
  const elements = new Map();
  const requests = [];
  let launchResponses = [launchResponse];

  class FakeElement {
    constructor() {
      this.children = [];
      this.listeners = {};
      this.dataset = {};
      this.disabled = false;
      this.hidden = false;
      this.textContent = "";
      this.value = "";
      this.innerHTML = "";
      this.attributes = {};
      this.classList = { remove() {}, add() {} };
    }

    addEventListener(name, listener) {
      this.listeners[name] = listener;
    }

    append(...children) {
      this.children.push(...children);
    }

    replaceChildren(...children) {
      this.children = children;
      this.textContent = "";
    }

    setAttribute(name, value) {
      this.attributes[name] = String(value);
    }

    closest(selector) {
      if (selector === ".eeee-plugin-status") return document.querySelector("#eeee-plugin-surface");
      return selector === "button[data-plugin-id]" && this.dataset.pluginId ? this : null;
    }

    scrollIntoView() {}

    focus() {}
  }

  const document = {
    documentElement: new FakeElement(),
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, new FakeElement());
      return elements.get(selector);
    },
    querySelectorAll() {
      return [];
    },
    createElement() {
      return new FakeElement();
    },
  };
  const localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
  const fetch = async (url, options = {}) => {
    const path = String(url);
    requests.push({ path, options });
    if (path === "/api/desktop/state") {
      return response({ controlCenter: { jobs: [], memory: {}, plugins: [], verification: {} } });
    }
    if (path.startsWith("/api/runs?")) return response([]);
    if (path.includes("/launch")) {
      const next = launchResponses.shift();
      if (!next) throw new Error("Unexpected launch request");
      return next;
    }
    return response([]);
  };

  const context = vm.createContext({ document, localStorage, fetch, setTimeout, clearTimeout });
  vm.runInContext(appSource, context, { filename: "app.js" });

  async function flush() {
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
  }

  async function renderOpenPlugin() {
    await flush();
    vm.runInContext(
      'renderEeeePluginStatus([{ pluginId: "eeee-chat-history", name: "채팅 기록", description: "기록", status: "connected", nextAction: "open" }])',
      context,
    );
  }

  return {
    context,
    elements,
    requests,
    flush,
    renderOpenPlugin,
    get(selector) { return document.querySelector(selector); },
  };
}

function clickPluginOpen(harness) {
  const installed = harness.get("#eeee-installed-plugin-list");
  const button = installed.children[0].children.at(-1);
  const surface = harness.get("#eeee-plugin-surface").listeners.click;
  return surface({ target: { closest: () => button } });
}

test("open action launches the installed chat history plugin and shows a web handoff", async () => {
  const harness = createHarness(response({
    pluginId: "eeee-chat-history",
    entrypoint: "C:\\plugins\\eeee_chat_history\\main.py",
  }));
  await harness.renderOpenPlugin();

  const installed = harness.get("#eeee-installed-plugin-list");
  assert.equal(installed.children[0].children.at(-1).textContent, "열기");

  await clickPluginOpen(harness);

  const launch = harness.requests.find((request) => request.path.endsWith("/api/plugins/eeee-chat-history/launch"));
  assert.ok(launch, "open should call the existing launch endpoint");
  assert.equal(launch.options.method, undefined);
  assert.match(harness.get("#eeee-control-status").textContent, /데스크톱에서 .*열 수 있도록 준비됨/);
  assert.doesNotMatch(harness.get("#eeee-control-status").textContent, /C:\\plugins\\/);
  assert.equal(harness.get("#eeee-control-status").innerHTML, "", "entrypoint must be rendered as text");
});

test("open action reports malformed launch responses as retryable errors", async () => {
  const harness = createHarness(response({ pluginId: "eeee-chat-history" }));
  await harness.renderOpenPlugin();

  await clickPluginOpen(harness);

  assert.equal(harness.get("#eeee-control-status").className, "status error");
  assert.match(harness.get("#eeee-control-status").textContent, /열지 못했습니다/);
  assert.match(harness.get("#eeee-control-status").textContent, /다시 시도/);
});

test("open action reports launch service failures as retryable errors", async () => {
  const harness = createHarness(response({ detail: "Plugin platform is unavailable" }, false));
  await harness.renderOpenPlugin();

  await clickPluginOpen(harness);

  assert.equal(harness.get("#eeee-control-status").className, "status error");
  assert.match(harness.get("#eeee-control-status").textContent, /다시 시도/);
  assert.match(harness.get("#eeee-control-status").textContent, /Plugin platform is unavailable/);
});
