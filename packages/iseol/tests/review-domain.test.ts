import assert from "node:assert/strict";
import test from "node:test";
import { changedLinesFromPatch, filterReviewFindings } from "../src/services/review/review-filter.js";
import { reviewResultSchema } from "../src/services/review/review-types.js";
import { renderReviewBody } from "../src/services/review/review-render.js";

test("changed line parser tracks added right-side lines", () => {
  const patch = "@@ -10,2 +10,3 @@\n old\n+added\n context";
  assert.deepEqual([...changedLinesFromPatch("src/a.ts", patch)], ["src/a.ts:11"]);
});

test("review filter removes low-confidence, duplicate and out-of-diff findings", () => {
  const changed = new Set(["src/a.ts:11", "src/a.ts:12"]);
  const result = reviewResultSchema.parse({ summary: ["핵심"], findings: [
    { filePath: "src/a.ts", line: 11, severity: "major", category: "correctness", confidence: 0.95, explanation: "버그" },
    { filePath: "src/a.ts", line: 11, severity: "major", category: "correctness", confidence: 0.95, explanation: "버그" },
    { filePath: "src/a.ts", line: 12, severity: "minor", category: "maintainability", confidence: 0.5, explanation: "낮은 확신" },
    { filePath: "src/a.ts", line: 99, severity: "major", category: "correctness", confidence: 0.99, explanation: "diff 밖" },
  ]});
  assert.equal(filterReviewFindings(result, changed).findings.length, 1);
});

test("ordinary reviews cap inline findings at five", () => {
  const changed = new Set(Array.from({ length: 8 }, (_, i) => `src/a.ts:${i + 1}`));
  const result = reviewResultSchema.parse({ summary: ["요약"], findings: Array.from({ length: 8 }, (_, i) => ({
    filePath: "src/a.ts", line: i + 1, severity: "major", category: "correctness", confidence: 0.9, explanation: `문제 ${i}`,
  })) });
  assert.equal(filterReviewFindings(result, changed).findings.length, 5);
});

test("review body is compact and has a clean zero-finding state", () => {
  const body = renderReviewBody({ summary: [], findings: [] });
  assert.match(body, /이설 Code Review/);
  assert.match(body, /문제를 찾지 못했습니다/);
  assert.doesNotMatch(body, /Overall|10점|Score/);
});

import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { ReviewStateStore } from "../src/services/review/review-state.js";

test("review state deduplicates repository pull request and head sha", async () => {
  const dir = await mkdtemp(join(tmpdir(), "iseol-review-"));
  const store = new ReviewStateStore(join(dir, "state.json"));
  assert.equal(await store.hasReviewed("o/r", 12, "abc"), false);
  await store.markReviewed("o/r", 12, "abc");
  assert.equal(await store.hasReviewed("o/r", 12, "abc"), true);
  assert.equal(await store.hasReviewed("o/r", 12, "def"), false);
  await rm(dir, { recursive: true, force: true });
});

import { buildReviewContext, isReviewablePath } from "../src/services/review/github-review.js";

test("review context skips lock and generated files", () => {
  assert.equal(isReviewablePath("package-lock.json"), false);
  assert.equal(isReviewablePath("dist/app.js"), false);
  assert.equal(isReviewablePath("src/app.ts"), true);
  const context = buildReviewContext([
    { filename: "package-lock.json", patch: "+ignored" },
    { filename: "src/app.ts", patch: "@@ -1 +1 @@\n-old\n+new" },
  ]);
  assert.match(context, /src\/app.ts/);
  assert.doesNotMatch(context, /package-lock/);
});
