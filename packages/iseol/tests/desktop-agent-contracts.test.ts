import assert from "node:assert/strict";
import test from "node:test";
import {
  ISEOL_DESKTOP_PROTOCOL_VERSION,
  assertDesktopProtocolVersion,
  assertDesktopTaskPack,
} from "../src/desktop-agent/contracts.js";

function basePack() {
  return {
    version: 1,
    jobId: "job-001",
    runId: "run-001",
    stage: "TEST",
    attempt: 1,
    agentId: "agent-001",
    workspaceRoot: "C:/repo",
    idempotencyKey: "test:run-001",
    leaseUntil: "2026-09-08T01:10:00.000Z",
    operations: [{ id: "op-1", type: "READ_FILE", path: "README.md" }],
  } as const;
}

test("desktop protocol version is strict", () => {
  assert.equal(ISEOL_DESKTOP_PROTOCOL_VERSION, 1);
  assert.doesNotThrow(() => assertDesktopProtocolVersion(1));
  assert.throws(() => assertDesktopProtocolVersion(2), /Unsupported Iseol Desktop protocol version/);
});

test("CHECK_HTTP accepts preview URLs but rejects unsafe URL syntax and timeouts", () => {
  const check = (url: string, timeoutMs = 1_000) => ({
    ...basePack(),
    operations: [{ id: "http", type: "CHECK_HTTP", url, timeoutMs }],
  });

  assert.doesNotThrow(() => assertDesktopTaskPack(check("http://127.0.0.1:3000/health?ready=1#preview")));
  assert.doesNotThrow(() => assertDesktopTaskPack(check("https://preview.example.test/result")));
  assert.doesNotThrow(() => assertDesktopTaskPack(check("http://127.0.0.1:3000/health", 2_147_483_647)));

  for (const url of [
    "ftp://preview.example.test/result",
    "file:///C:/secret.txt",
    "preview.example.test/result",
    " http://127.0.0.1:3000/health",
    "http://127.0.0.1:3000/health ",
    "http://user:password@preview.example.test/result",
    "http://@preview.example.test/result",
    "http://preview.example.test\\result",
    "http://preview.example.test/%5Cresult",
    "http://preview.example.test/result?token=secret-value",
    "http://preview.example.test/result?api_key=secret-value",
    "http://preview.example.test/result?client_secret=secret-value",
    "http://preview.example.test/result?id_token=secret-value",
    "http://preview.example.test/result?auth_token=secret-value",
    "http://preview.example.test/result?bearer_token=secret-value",
    "http://preview.example.test/result?x-api-key=secret-value",
    "http://preview.example.test/result?oauth_token=secret-value",
    "http://preview.example.test/result?x-auth-token=secret-value",
    "http://preview.example.test/result?api-token=secret-value",
    "http://preview.example.test/result?secret_key=secret-value",
    "http://preview.example.test/result?session_token=secret-value",
    "http://preview.example.test/result?jwt=secret-value",
    "http://preview.example.test/result?x-api-token=secret-value",
    "http://preview.example.test/result?x-access-token=secret-value",
    "http://preview.example.test/result?authorization_token=secret-value",
    "http://preview.example.test/result?csrf_token=secret-value",
    "http://preview.example.test/result?oauth2_token=secret-value",
    "http://preview.example.test/result?x-oauth-token=secret-value",
    "http://preview.example.test/result?oauth_access_token=secret-value",
    "http://preview.example.test/result#access_token=secret-value",
    "http://preview.example.test/result#oauth_token=secret-value",
    "http://preview.example.test/result#access_token%3Dsecret-value",
    "http://preview.example.test/result#foo%26oauth_token%3Dsecret-value",
    "http://preview.example.test/result#access_token%3Dsecret%ZZ",
    "http://preview.example.test/result#access_token%ZZ=secret-value",
    `http://preview.example.test/result${String.fromCharCode(10)}`,
  ]) {
    assert.throws(() => assertDesktopTaskPack(check(url)), /CHECK_HTTP|URL|unsafe|credential|control/i, url);
  }

  for (const timeoutMs of [0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY, 2_147_483_648, Number.MAX_SAFE_INTEGER]) {
    assert.throws(() => assertDesktopTaskPack(check("http://127.0.0.1:3000/health", timeoutMs)), /timeout/i, String(timeoutMs));
  }
});

test("task pack requires stable execution identity", () => {
  for (const field of ["jobId", "runId", "workspaceRoot", "idempotencyKey"] as const) {
    const pack = { ...basePack(), [field]: "" };
    assert.throws(() => assertDesktopTaskPack(pack), new RegExp(field));
  }

  assert.throws(
    () => assertDesktopTaskPack({ ...basePack(), leaseUntil: "not-a-date" }),
    /leaseUntil/,
  );
});

test("task pack rejects unsupported operations and duplicate operation ids", () => {
  assert.throws(
    () => assertDesktopTaskPack({
      ...basePack(),
      operations: [{ id: "op-1", type: "DELETE_FILE", path: "README.md" }],
    }),
    /Unsupported Desktop operation type/,
  );

  assert.throws(
    () => assertDesktopTaskPack({
      ...basePack(),
      operations: [
        { id: "op-1", type: "READ_FILE", path: "a.txt" },
        { id: "op-1", type: "LIST_DIRECTORY", path: "." },
      ],
    }),
    /duplicate operation id/i,
  );
});

test("mutation-capable task packs require policy provenance", () => {
  const mutation = {
    ...basePack(),
    operations: [{ id: "op-1", type: "APPLY_PATCH", path: "src/app.ts", patch: "@@" }],
  };
  assert.throws(() => assertDesktopTaskPack(mutation), /policyDigest/);

  assert.throws(
    () => assertDesktopTaskPack({ ...mutation, policyDigest: "a".repeat(64), policySources: [] }),
    /policySources/,
  );

  assert.doesNotThrow(() => assertDesktopTaskPack({
    ...mutation,
    policyDigest: "a".repeat(64),
    policySources: [{
      kind: "project-harness",
      path: "C:/repo/docs/HARNESS_ENGINEERING.md",
      sha256: "b".repeat(64),
      required: true,
    }],
  }));
});

test("read-only task packs do not require policy provenance", () => {
  assert.doesNotThrow(() => assertDesktopTaskPack(basePack()));
});

test("desktop operations reject unknown fields and destructive Git through RUN_PROCESS", () => {
  assert.throws(
    () => assertDesktopTaskPack({
      ...basePack(),
      policyDigest: "a".repeat(64),
      policySources: [{ kind: "project-harness", path: "C:/repo/docs/HARNESS_ENGINEERING.md", sha256: "b".repeat(64), required: true }],
      operations: [{ id: "op-1", type: "RUN_PROCESS", purpose: "test", cwd: ".", executable: "git", args: ["status"], timeoutMs: 1_000, shell: true }],
    }),
    /unknown field/i,
  );
  assert.throws(
    () => assertDesktopTaskPack({
      ...basePack(),
      policyDigest: "a".repeat(64),
      policySources: [{ kind: "project-harness", path: "C:/repo/docs/HARNESS_ENGINEERING.md", sha256: "b".repeat(64), required: true }],
      operations: [{ id: "op-1", type: "RUN_PROCESS", purpose: "test", cwd: ".", executable: "git", args: ["reset", "--hard", "HEAD~1"], timeoutMs: 1_000 }],
    }),
    /destructive Git process/i,
  );
  for (const args of [
    ["-C", "C:/repo", "reset", "--hard"],
    ["-c", "core.autocrlf=false", "clean", "-fd"],
  ]) {
    assert.throws(
      () => assertDesktopTaskPack({
        ...basePack(),
        policyDigest: "a".repeat(64),
        policySources: [{ kind: "project-harness", path: "C:/repo/docs/HARNESS_ENGINEERING.md", sha256: "b".repeat(64), required: true }],
        operations: [{ id: "op-1", type: "RUN_PROCESS", purpose: "test", cwd: ".", executable: "git", args, timeoutMs: 1_000 }],
      }),
      /destructive Git process/i,
    );
  }
});

test("Git publish and remote inspection flags are strict booleans", () => {
  assert.throws(() => assertDesktopTaskPack({
    ...basePack(),
    policyDigest: "a".repeat(64),
    policySources: [{ kind: "project-harness", path: "C:/repo/docs/HARNESS_ENGINEERING.md", sha256: "b".repeat(64), required: true }],
    operations: [{ id: "commit", type: "GIT_COMMIT", cwd: ".", message: "feat: publish", publish: "true" }],
  }), /publish/i);

  assert.throws(() => assertDesktopTaskPack({
    ...basePack(),
    operations: [{ id: "inspect", type: "GIT_INSPECT", cwd: ".", includeRemote: "yes" }],
  }), /includeRemote/i);
});

test("RUN_PROCESS requires a bounded test or build purpose", () => {
  const policy = {
    policyDigest: "a".repeat(64),
    policySources: [{ kind: "project-harness", path: "C:/repo/docs/HARNESS_ENGINEERING.md", sha256: "b".repeat(64), required: true }],
  };
  const process = { id: "op-1", type: "RUN_PROCESS", cwd: ".", executable: "npm", args: ["test"], timeoutMs: 1_000 };
  assert.throws(() => assertDesktopTaskPack({ ...basePack(), ...policy, operations: [process] }), /purpose/i);
  assert.throws(() => assertDesktopTaskPack({ ...basePack(), ...policy, operations: [{ ...process, purpose: "deploy" }] }), /purpose/i);
  assert.doesNotThrow(() => assertDesktopTaskPack({ ...basePack(), ...policy, operations: [{ ...process, purpose: "test" }] }));
  assert.throws(
    () => assertDesktopTaskPack({ ...basePack(), ...policy, operations: [{ ...process, purpose: "test", args: ["install"] }] }),
    /not allowed|bounded|test/i,
  );
});
