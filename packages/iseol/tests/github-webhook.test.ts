import assert from "node:assert/strict";
import test from "node:test";
import { createHmac } from "node:crypto";
import { shouldReviewPullRequestAction, verifyGitHubSignature } from "../src/services/github-webhook.js";

test("github webhook signature verification uses sha256 hmac", () => {
  const body = Buffer.from('{"ok":true}');
  const signature = `sha256=${createHmac("sha256", "secret").update(body).digest("hex")}`;
  assert.equal(verifyGitHubSignature("secret", body, signature), true);
  assert.equal(verifyGitHubSignature("wrong", body, signature), false);
});

test("only opened reopened and synchronize pull request actions trigger review", () => {
  assert.equal(shouldReviewPullRequestAction("opened"), true);
  assert.equal(shouldReviewPullRequestAction("reopened"), true);
  assert.equal(shouldReviewPullRequestAction("synchronize"), true);
  assert.equal(shouldReviewPullRequestAction("closed"), false);
});

import { buildAutomationWebhookUrl, isDiscordProjectWebhookUrl, parseGitHubRepository } from "../src/services/github.js";

test("automation webhook url targets the signed github events endpoint", () => {
  assert.equal(buildAutomationWebhookUrl("https://iseol.example.com/"), "https://iseol.example.com/github/events");
  assert.equal(
    buildAutomationWebhookUrl("https://iseol.example.com/discord/?tenant=alpha#ignored"),
    "https://iseol.example.com/discord/github/events",
  );
});

test("automation webhook url rejects unsafe public base URL authorities", () => {
  for (const value of [
    "http://iseol.example.com",
    "https://user:password@iseol.example.com",
    "https://iseol.example.com:8443",
    "https://iseol.example.com\\@attacker.example.com",
    "https://iseol.example.com/%5C@attacker.example.com",
    "not a url",
  ]) {
    assert.throws(() => buildAutomationWebhookUrl(value), /PUBLIC_BASE_URL/);
  }
});

test("discord project webhook identities require a canonical HTTPS webhook path", () => {
  assert.equal(isDiscordProjectWebhookUrl("https://discord.com/api/webhooks/123456789012345678/token/github"), true);
  assert.equal(isDiscordProjectWebhookUrl("https://www.discordapp.com/api/webhooks/123/token/github"), true);

  for (const value of [
    "http://discord.com/api/webhooks/123/token/github",
    "https://user:password@discord.com/api/webhooks/123/token/github",
    "https://discord.com:8443/api/webhooks/123/token/github",
    "https://discord.com/api/webhooks/123/token/github?scope=private",
    "https://discord.com/api/webhooks/123/token/github?",
    "https://discord.com/api/webhooks/123/token/github#private",
    "https://discord.com/api/webhooks/123/token/github#",
    "https://discord.com/api/webhooks/not-a-snowflake/token/github",
    "https://discord.com/prefix/api/webhooks/123/token/github",
    "https://discord.com/api/webhooks/123/token/extra/github",
    "https://discord.com/api/webhooks/123/token/./github",
    "https://discord.com/api/webhooks/123/junk/../token/github",
    "https://discord.com/api/webhooks/123/to\nken/github",
    "https://discord.com/api/webhooks/123/to\tken/github",
    "https://discord.com/api/webhooks/123/to%2Fken/github",
    "https://discord.com\\@attacker.example.com/api/webhooks/123/token/github",
    "https://discord.com/api/webhooks/123/to%5Cken/github",
    "https://discord.com.evil.example/api/webhooks/123/token/github",
  ]) {
    assert.equal(isDiscordProjectWebhookUrl(value), false, value);
  }
});

test("github repository identities reject malformed and path-like input", () => {
  assert.deepEqual(parseGitHubRepository("openai/iseol"), {
    owner: "openai",
    repo: "iseol",
    url: "https://github.com/openai/iseol",
  });
  assert.deepEqual(parseGitHubRepository("https://github.com/openai/iseol"), {
    owner: "openai",
    repo: "iseol",
    url: "https://github.com/openai/iseol",
  });
  assert.deepEqual(parseGitHubRepository("github/.github"), {
    owner: "github",
    repo: ".github",
    url: "https://github.com/github/.github",
  });

  for (const value of [
    "https://github.com/openai/%E0%A4%A",
    "https://github.com/openai/iseol%2Fsecret",
    "https://github.com/openai%2Fsecret/iseol",
    "openai\\iseol",
    "https://github.com/openai/iseol%5Csecret",
    "https://github.com/openai/iseol?redirect=/private",
    "https://github.com/openai/iseol#private",
    "openai/iseol?",
    "openai/iseol#",
    "https://github.com/openai/iseol?",
    "https://github.com/openai/iseol#",
    "https://github.com/openai/repo/../secret",
    "https://github.com/openai/./repo",
    "https://github.com/openai//repo",
    "openai/.git",
    "openai/..git",
    "openai/.git.git",
    "https://github.com/openai/repo%3Fprivate",
    "https://github.com/openai/repo%23private",
    "https://github.com/openai/repo%252Fsecret",
    "https://github.com/openai/repo%255Csecret",
  ]) {
    assert.throws(() => parseGitHubRepository(value), /GitHub 저장소/);
  }
});
