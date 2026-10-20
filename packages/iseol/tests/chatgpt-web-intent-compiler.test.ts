import assert from "node:assert/strict";
import test from "node:test";
import { resolve } from "node:path";
import type { HarnessRuntimeRunEnvelope } from "../src/harness/contracts.js";
import type { WebWorkerSession, DesktopIntent } from "../src/chatgpt-web/contracts.js";
import {
  buildValidatedPatchIntent,
  compileDesktopIntentToTaskPack,
  validateDesktopIntent,
} from "../src/chatgpt-web/intent-compiler.js";

const root = resolve("C:/tmp/iseol-web-intent");
const policySha256 = "a".repeat(64);
const sourceSha256 = "b".repeat(64);

const run: HarnessRuntimeRunEnvelope = {
  version: 1,
  request: { version: 1, runId: "run-1", mode: "project-workspace", objective: "Implement feature", targetRoot: root },
  preflight: { version: 1, runId: "run-1", status: "ready", policy: { version: 1, loadedAt: "2026-09-08T01:00:00.000Z", effectiveSha256: policySha256, sources: [{ kind: "iseol-global", path: resolve(root, "docs/HARNESS_ENGINEERING.md"), sha256: sourceSha256, content: "secret policy body" }] } },
  state: { version: 1, stage: "IMPLEMENT", status: "RUNNING", completedStages: [], skippedStages: [], updatedAt: "2026-09-08T01:00:00.000Z" },
  evidence: [],
  updatedAt: "2026-09-08T01:00:00.000Z",
};
const session: WebWorkerSession = {
  version: 1, sessionId: "session-1", runId: "run-1", stage: "IMPLEMENT", generation: 2,
  policySha256, status: "ready", createdAt: "2026-09-08T01:00:00.000Z",
};
const base = {
  version: 1 as const,
  intentId: "intent-1",
  runId: "run-1",
  stage: "IMPLEMENT" as const,
  workspaceRoot: root,
  policySha256,
};
const context = { run, session, resultGeneration: 2, commitAuthorized: false };

test("validated patch intent is runtime-owned and preserves the normalized payload", () => {
  const payload = [
    "diff --git a/src/index.ts b/src/index.ts",
    "--- a/src/index.ts",
    "+++ b/src/index.ts",
    "@@ -1 +1 @@",
    "-old",
    "+new",
    "",
  ].join("\r\n");

  const intent = buildValidatedPatchIntent(context, payload);

  assert.deepEqual(intent, {
    ...base,
    intentId: "implement-patch-eaf79b8ece9e515be0e9753e",
    kind: "PROPOSE_PATCH",
    path: "src/index.ts",
    patch: payload.replaceAll("\r\n", "\n"),
  });
  assert.equal((compileDesktopIntentToTaskPack(context, intent, "agent-1", "2026-09-08T01:00:00.000Z").operations[0] as any).patch, payload.replaceAll("\r\n", "\n"));
});

test("malformed patch is rejected before a PROPOSE_PATCH intent can be built", () => {
  const malformed = [
    "diff --git a/src/index.ts b/src/index.ts",
    "--- a/src/index.ts",
    "+++ b/src/index.ts",
    "@@ -1 +1 @@",
    "-old",
    "+new",
    "+extra",
    "",
  ].join("\n");

  assert.throws(() => buildValidatedPatchIntent(context, malformed), /hunk.*count/i);
  assert.throws(
    () => buildValidatedPatchIntent(context, malformed.replaceAll("src/index.ts", "../secret.txt")),
    /relative|workspace|path/i,
  );
});

test("intent validation binds run stage generation policy and workspace", () => {
  const intent: DesktopIntent = { ...base, kind: "GIT_INSPECT", cwd: "." };
  assert.doesNotThrow(() => validateDesktopIntent(context, intent));
  assert.throws(() => validateDesktopIntent({ ...context, resultGeneration: 1 }, intent), /generation/i);
  assert.throws(() => validateDesktopIntent(context, { ...intent, runId: "run-2" }), /run/i);
  assert.throws(() => validateDesktopIntent(context, { ...intent, stage: "PLAN" }), /stage/i);
  assert.throws(() => validateDesktopIntent(context, { ...intent, policySha256: "c".repeat(64) }), /policy/i);
  assert.throws(() => validateDesktopIntent(context, { ...intent, workspaceRoot: resolve(root, "other") }), /workspace/i);
});

test("commit requires explicit authorization while reasoning intents are bounded", () => {
  const commit: DesktopIntent = { ...base, kind: "REQUEST_COMMIT", cwd: ".", message: "feat: safe commit" };
  assert.throws(() => validateDesktopIntent(context, commit), /commit.*authorized/i);
  assert.doesNotThrow(() => validateDesktopIntent({ ...context, commitAuthorized: true }, commit));

  const processIntent: DesktopIntent = { ...base, kind: "RUN_TEST", cwd: ".", executable: "node", args: ["--test"], timeoutMs: 1000 };
  assert.doesNotThrow(() => validateDesktopIntent(context, processIntent));
  assert.throws(() => validateDesktopIntent(context, { ...processIntent, args: ["-e", "process.exit(0)"] }), /inline|eval/i);
  assert.throws(() => validateDesktopIntent(context, { ...processIntent, executable: "powershell.exe" }), /shell/i);
});
test("supported intents compile into only the matching Desktop operation", () => {
  const cases: Array<[DesktopIntent, string]> = [
    [{ ...base, kind: "READ_CONTEXT", path: "src/index.ts" }, "READ_FILE"],
    [{ ...base, kind: "PROPOSE_PATCH", path: "src/index.ts", patch: "--- a/src/index.ts\n+++ b/src/index.ts\n@@ -1 +1 @@\n-old\n+new\n" }, "APPLY_PATCH"],
    [{ ...base, kind: "RUN_TEST", cwd: ".", executable: "npm.cmd", args: ["test"], timeoutMs: 30_000 }, "RUN_PROCESS"],
    [{ ...base, kind: "RUN_BUILD", cwd: ".", executable: "npm.cmd", args: ["run", "build"], timeoutMs: 30_000 }, "RUN_PROCESS"],
    [{ ...base, kind: "GIT_INSPECT", cwd: "." }, "GIT_INSPECT"],
    [{ ...base, kind: "CHECK_HTTP", url: "http://127.0.0.1:3000/health", timeoutMs: 1000 }, "CHECK_HTTP"],
  ];
  for (const [intent, expectedType] of cases) {
    const pack = compileDesktopIntentToTaskPack(context, intent, "agent-1", "2026-09-08T01:00:00.000Z");
    assert.equal(pack.operations.length, 1);
    assert.equal(pack.operations[0]?.type, expectedType);
    assert.equal(pack.idempotencyKey, `web-intent:run-1:${intent.intentId}`);
    assert.equal(pack.workspaceRoot, root);
    assert.equal(pack.policyDigest, policySha256);
    assert.deepEqual(pack.policySources, [{ kind: "iseol-global", path: resolve(root, "docs/HARNESS_ENGINEERING.md"), sha256: sourceSha256, required: true }]);
    assert.equal(JSON.stringify(pack).includes("secret policy body"), false);
  }
});

test("commit compilation preserves expected head and requires authorization", () => {
  const commit: DesktopIntent = { ...base, kind: "REQUEST_COMMIT", cwd: ".", message: "feat: safe commit", expectedHead: "abc123" };
  const pack = compileDesktopIntentToTaskPack({ ...context, commitAuthorized: true }, commit, "agent-1", "2026-09-08T01:00:00.000Z");
  assert.deepEqual(pack.operations[0], { id: "intent-1", type: "GIT_COMMIT", cwd: ".", message: "feat: safe commit", expectedHead: "abc123" });
});

test("relative paths cannot escape the Run workspace", () => {
  assert.throws(() => validateDesktopIntent(context, { ...base, kind: "READ_CONTEXT", path: "../secret.txt" }), /outside|relative|workspace/i);
  assert.throws(() => validateDesktopIntent(context, { ...base, kind: "GIT_INSPECT", cwd: resolve(root, "src") }), /relative/i);
});

test("absolute cwd rejection tells reasoning to use dot for the workspace root", () => {
  const intent: DesktopIntent = { ...base, kind: "GIT_INSPECT", cwd: root };
  assert.throws(
    () => validateDesktopIntent(context, intent),
    /workspace-relative.*use ['"]?\.['"]?.*workspace root/i,
  );
});


test("test and build intents compile to purpose-bound process operations", () => {
  const testIntent: DesktopIntent = { ...base, kind: "RUN_TEST", cwd: ".", executable: "npm", args: ["test"], timeoutMs: 30_000 };
  const buildIntent: DesktopIntent = { ...base, kind: "RUN_BUILD", cwd: ".", executable: "npm", args: ["run", "build"], timeoutMs: 30_000 };
  assert.equal((compileDesktopIntentToTaskPack(context, testIntent, "agent-1", "2026-09-08T01:00:00.000Z").operations[0] as any).purpose, "test");
  assert.equal((compileDesktopIntentToTaskPack(context, buildIntent, "agent-1", "2026-09-08T01:00:00.000Z").operations[0] as any).purpose, "build");
  assert.throws(
    () => validateDesktopIntent(context, { ...testIntent, args: ["install"] }),
    /not allowed|bounded|test/i,
  );
});
