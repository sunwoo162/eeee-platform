import assert from "node:assert/strict";
import test from "node:test";
import { GleaveMobileClient, MemoryTokenStore } from "../src/client.js";

test("mobile client pairs, stores the Desktop token, and resumes event cursors", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Request[] = [];
  globalThis.fetch = async (input, init) => {
    const request = new Request(input, init);
    calls.push(request);
    if (request.url.endsWith("/api/mobile/pair")) {
      return new Response(JSON.stringify({ deviceId: "mobile-1", deviceName: "Phone", accessToken: "token-1" }), { status: 200 });
    }
    return new Response(JSON.stringify({ cursor: 3, events: [{ cursor: 3, kind: "project.completed", payload: {}, createdAt: "2026-10-06T00:00:00Z" }], hasGap: true, oldestCursor: 2 }), { status: 200 });
  };

  try {
    const store = new MemoryTokenStore();
    const client = new GleaveMobileClient("http://desktop.local/", store);
    await client.pair("123456", "Phone");
    const batch = await client.events(2);

    assert.equal(store.get(), "token-1");
    assert.equal(batch.events[0]?.cursor, 3);
    assert.equal(batch.hasGap, true);
    assert.equal(batch.oldestCursor, 2);
    assert.equal(calls[1]?.headers.get("X-Gleave-Bridge-Token"), "token-1");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("mobile client sends stable conversation/request ids and reads history", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Request[] = [];
  globalThis.fetch = async (input, init) => {
    const request = new Request(input, init);
    calls.push(request);
    if (request.url.endsWith("/api/mobile/pair")) {
      return new Response(JSON.stringify({ deviceId: "mobile-1", deviceName: "Phone", accessToken: "token-1" }), { status: 200 });
    }
    if (request.url.includes("/messages")) {
      return new Response(JSON.stringify({ conversationId: "chat-1", messageCount: 2, turns: [], nextBeforeId: null }), { status: 200 });
    }
    if (request.url.includes("/conversations")) {
      return new Response(JSON.stringify([{ conversationId: "chat-1", messageCount: 2, preview: "안녕", updatedAt: "2026-10-06T00:00:00Z" }]), { status: 200 });
    }
    return new Response(JSON.stringify({ status: "completed" }), { status: 200 });
  };

  try {
    const client = new GleaveMobileClient("http://desktop.local/", new MemoryTokenStore());
    await client.pair("123456", "Phone");
    await client.assistantRoute("계속해", undefined, { conversationId: "chat-1", requestId: "request-1" });
    const summaries = await client.conversations("계속", 20, "2026-10-06T00:00:00Z", "chat-1");
    const transcript = await client.conversation("chat-1", 20, 3);

    const routeBody = await calls[1]?.clone().json() as Record<string, unknown>;
    assert.equal(routeBody.conversationId, "chat-1");
    assert.equal(routeBody.requestId, "request-1");
    assert.equal(summaries[0]?.conversationId, "chat-1");
    assert.match(calls[2]?.url ?? "", /beforeUpdatedAt=2026-10-06T00%3A00%3A00Z/);
    assert.match(calls[2]?.url ?? "", /beforeConversationId=chat-1/);
    assert.equal(transcript.conversationId, "chat-1");
    assert.match(calls[3]?.url ?? "", /beforeId=3/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
