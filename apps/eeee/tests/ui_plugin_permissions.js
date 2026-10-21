import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const appSource = fs.readFileSync(new URL("../app/static/app.js", import.meta.url), "utf8");

function response(body, ok = true) {
  return { ok, json: async () => body };
}

class FakeElement {
  constructor(tagName = "div", document) {
    this.tagName = tagName.toUpperCase();
    this.document = document;
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.attributes = {};
    this.classList = { add() {}, remove() {} };
    this.className = "";
    this.disabled = false;
    this.hidden = false;
    this.checked = false;
    this.type = "";
    this.value = "";
    this.textContent = "";
    this.innerHTML = "";
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
    if (selector === ".eeee-plugin-status") return this.document.querySelector("#eeee-plugin-surface");
    if (selector === "button[data-plugin-id]" && this.tagName === "BUTTON") return this;
    if (selector === "input[data-plugin-id]" && this.tagName === "INPUT") return this;
    return null;
  }

  focus() {}
  scrollIntoView() {}
}

function createHarness({ catalogPlugin, statePlugin }) {
  const elements = new Map();
  const requests = [];
  const document = {
    documentElement: new FakeElement("html", null),
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, new FakeElement("div", document));
      return elements.get(selector);
    },
    querySelectorAll() {
      return [];
    },
    createElement(tagName) {
      return new FakeElement(tagName, document);
    },
  };
  document.documentElement.document = document;

  const window = {
    location: { search: "", href: "" },
    open() {
      return { location: { href: "" } };
    },
  };
  const localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
  const fetch = async (url, options = {}) => {
    const path = String(url);
    requests.push({ path, options });
    if (path === "/api/desktop/state") {
      return response({ controlCenter: { jobs: [], memory: {}, plugins: [statePlugin], verification: {} } });
    }
    if (path === "/api/plugins/catalog") return response([catalogPlugin]);
    if (path.startsWith("/api/runs?")) return response([]);
    if (path.endsWith("/oauth/start")) {
      return response({ authorizationUrl: "https://provider.example/authorize", state: "oauth-state" });
    }
    return response([]);
  };

  const context = vm.createContext({ document, window, localStorage, fetch, setTimeout, clearTimeout });
  vm.runInContext(appSource, context, { filename: "app.js" });

  async function flush() {
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
  }

  function render(plugin = statePlugin) {
    vm.runInContext(`renderEeeePluginStatus(${JSON.stringify([plugin])})`, context);
  }

  return {
    context,
    document,
    requests,
    flush,
    render,
    get(selector) { return document.querySelector(selector); },
    setCatalog(plugin) { catalogPlugin = plugin; },
  };
}

function collectElements(root, predicate, result = []) {
  for (const child of root.children || []) {
    if (predicate(child)) result.push(child);
    collectElements(child, predicate, result);
  }
  return result;
}

function collectText(root) {
  return [root.textContent || "", ...(root.children || []).map(collectText)].join(" ");
}

function createPlugin(overrides = {}) {
  return {
    id: "notion",
    pluginId: "notion",
    name: "Notion",
    description: "Notion pages connector",
    authMode: "oauth",
    permissions: ["pages.read", "pages.write"],
    permissionDetails: [
      { id: "pages.read", label: "페이지 읽기", description: "Notion 페이지를 읽습니다.", effect: "none", defaultApproved: true },
      { id: "pages.write", label: "페이지 쓰기", description: "Notion 페이지를 만들거나 수정합니다.", effect: "external", defaultApproved: false, requires: ["pages.read"] },
    ],
    approvedPermissions: [],
    status: "available",
    nextAction: "connect",
    ...overrides,
  };
}

test("OAuth cards default to read permissions and render catalog descriptions and side effects", async () => {
  const plugin = createPlugin();
  const harness = createHarness({ catalogPlugin: plugin, statePlugin: plugin });
  await harness.flush();
  harness.render(plugin);

  const inputs = collectElements(harness.get("#eeee-installed-plugin-list"), (element) => element.tagName === "INPUT");
  assert.deepEqual(inputs.map((input) => [input.dataset.permission, input.checked]), [
    ["pages.read", true],
    ["pages.write", false],
  ]);
  const renderedText = collectText(harness.get("#eeee-installed-plugin-list"));
  assert.match(renderedText, /Notion 페이지를 읽습니다/);
  assert.match(renderedText, /외부/);
});

test("existing approvedPermissions are used as the editable OAuth defaults", async () => {
  const plugin = createPlugin({ approvedPermissions: ["pages.write"] });
  const harness = createHarness({ catalogPlugin: plugin, statePlugin: plugin });
  await harness.flush();
  harness.render(plugin);

  const inputs = collectElements(harness.get("#eeee-installed-plugin-list"), (element) => element.tagName === "INPUT");
  assert.deepEqual(inputs.map((input) => [input.dataset.permission, input.checked]), [
    ["pages.read", true],
    ["pages.write", true],
  ]);
});

test("selecting a dependent permission automatically selects its requirements", async () => {
  const plugin = createPlugin({
    permissionDetails: createPlugin().permissionDetails.map((detail) => ({ ...detail, defaultApproved: false })),
  });
  const harness = createHarness({ catalogPlugin: plugin, statePlugin: plugin });
  await harness.flush();
  harness.render(plugin);

  let inputs = collectElements(harness.get("#eeee-installed-plugin-list"), (element) => element.tagName === "INPUT");
  const readInput = inputs.find((input) => input.dataset.permission === "pages.read");
  readInput.checked = false;
  const surface = harness.get("#eeee-plugin-surface");
  await surface.listeners.change({ target: readInput });
  const writeInput = collectElements(harness.get("#eeee-installed-plugin-list"), (element) => element.tagName === "INPUT")
    .find((input) => input.dataset.permission === "pages.write");
  writeInput.checked = true;
  await surface.listeners.change({ target: writeInput });

  inputs = collectElements(harness.get("#eeee-installed-plugin-list"), (element) => element.tagName === "INPUT");
  assert.deepEqual(inputs.map((input) => [input.dataset.permission, input.checked]), [
    ["pages.read", true],
    ["pages.write", true],
  ]);
});

test("deselecting a required permission removes dependent selection with a Korean message", async () => {
  const plugin = createPlugin({ approvedPermissions: ["pages.read", "pages.write"] });
  const harness = createHarness({ catalogPlugin: plugin, statePlugin: plugin });
  await harness.flush();
  harness.render(plugin);

  const readInput = collectElements(harness.get("#eeee-installed-plugin-list"), (element) => element.tagName === "INPUT")
    .find((input) => input.dataset.permission === "pages.read");
  readInput.checked = false;
  const surface = harness.get("#eeee-plugin-surface");
  await surface.listeners.change({ target: readInput });

  const inputs = collectElements(harness.get("#eeee-installed-plugin-list"), (element) => element.tagName === "INPUT");
  assert.deepEqual(inputs.map((input) => [input.dataset.permission, input.checked]), [
    ["pages.read", false],
    ["pages.write", false],
  ]);
  assert.match(harness.get("#eeee-control-status").textContent, /필수|권한/);
});

test("explicit defaultApproved values override the read-only fallback", async () => {
  const plugin = createPlugin({
    permissionDetails: [
      { id: "pages.read", label: "페이지 읽기", description: "읽기", effect: "none", defaultApproved: false },
      { id: "pages.write", label: "페이지 쓰기", description: "쓰기", effect: "external", defaultApproved: true, requires: ["pages.read"] },
    ],
  });
  const harness = createHarness({ catalogPlugin: plugin, statePlugin: plugin });
  await harness.flush();
  harness.render(plugin);

  const inputs = collectElements(harness.get("#eeee-installed-plugin-list"), (element) => element.tagName === "INPUT");
  assert.deepEqual(inputs.map((input) => [input.dataset.permission, input.checked]), [
    ["pages.read", true],
    ["pages.write", true],
  ]);
});

test("refresh prunes selected permissions that disappeared from the catalog", async () => {
  const plugin = createPlugin();
  const harness = createHarness({ catalogPlugin: plugin, statePlugin: plugin });
  await harness.flush();
  harness.render(plugin);

  const writeInput = collectElements(harness.get("#eeee-installed-plugin-list"), (element) => element.tagName === "INPUT")
    .find((input) => input.dataset.permission === "pages.write");
  writeInput.checked = true;
  await harness.get("#eeee-plugin-surface").listeners.change({ target: writeInput });
  harness.setCatalog(createPlugin({
    permissions: ["pages.read"],
    permissionDetails: [createPlugin().permissionDetails[0]],
    approvedPermissions: [],
  }));
  await harness.context.refreshEeeeControlCenter();
  await harness.flush();

  const button = collectElements(harness.get("#eeee-installed-plugin-list"), (element) => element.tagName === "BUTTON")[0];
  await harness.get("#eeee-plugin-surface").listeners.click({ target: { closest: () => button } });

  const request = harness.requests.find((item) => item.path.endsWith("/oauth/start"));
  assert.ok(request, "selected OAuth permissions should start OAuth");
  assert.deepEqual(JSON.parse(request.options.body), { approvedPermissions: ["pages.read"] });
});
