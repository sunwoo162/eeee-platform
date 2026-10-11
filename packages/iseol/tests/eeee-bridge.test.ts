import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { agentCorrectionPromptFor } from "../src/chatgpt-web/eeee-bridge.ts";

test("specialist correction prompt requires one strict action JSON object", () => {
  const prompt = agentCorrectionPromptFor("run-1", "structured result is not exactly one JSON value");

  assert.match(prompt.body, /ONLY the JSON object/);
  assert.match(prompt.body, /\"actions\"/);
  assert.match(prompt.body, /run-1/);
  assert.equal(prompt.sha256.length, 64);
});
test("recognizes recoverable ChatGPT turn races", async () => {
  const source = await readFile(new URL("../src/chatgpt-web/eeee-bridge.ts", import.meta.url), "utf8");
  assert.match(source, /pending-submission-missing/);
  assert.match(source, /newConversation: true/);
});

test("bridge includes bounded EEEE profile guidance in assistant prompts", async () => {
  const source = await readFile(new URL("../src/chatgpt-web/eeee-bridge.ts", import.meta.url), "utf8");
  assert.match(source, /profile\?: unknown/);
  assert.match(source, /Assistant profile \(style guidance only/);
  assert.match(source, /input\.profile/);
});
