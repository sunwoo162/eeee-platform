import assert from "node:assert/strict";
import test from "node:test";
import { GitHubScheduleSyncService } from "../src/services/github-schedule-sync.js";

class MemoryState {
  items = new Map<string, any>();
  locks = new Map<string, Promise<void>>();
  async find(key: string) { return this.items.get(key) ?? null; }
  async upsert(value: any) { this.items.set(value.externalKey, value); }
  async remove(key: string) { return this.items.delete(key); }
  async withMappingLock<T>(key: string, task: () => Promise<T>) {
    const previous = this.locks.get(key) ?? Promise.resolve();
    let release!: () => void;
    const current = new Promise<void>((resolveRelease) => { release = resolveRelease; });
    this.locks.set(key, current);
    await previous;
    try {
      return await task();
    } finally {
      release();
      if (this.locks.get(key) === current) this.locks.delete(key);
    }
  }
}

test("milestone synchronization creates once then updates the same event", async () => {
  const calls: string[] = [];
  const state = new MemoryState();
  const calendar = {
    async createEvent() { calls.push("create"); return { id: "event-1", htmlLink: "" }; },
    async updateEvent() { calls.push("update"); return { id: "event-1", htmlLink: "" }; },
    async deleteEvent() { calls.push("delete"); },
  };
  const service = new GitHubScheduleSyncService(calendar, state as any);
  const milestone = { number: 3, title: "MVP", dueOn: "2026-09-10T15:00:00Z", state: "open" as const, htmlUrl: "https://github.com/o/r/milestone/3" };
  await service.syncMilestone("project", "calendar", "o/r", milestone);
  await service.syncMilestone("project", "calendar", "o/r", milestone);
  assert.deepEqual(calls, ["create", "update"]);
});

test("concurrent milestone synchronization publishes one event before updating it", async () => {
  const calls: string[] = [];
  const state = new MemoryState();
  const calendar = {
    async createEvent() {
      calls.push("create");
      await new Promise((resolveWait) => setTimeout(resolveWait, 25));
      return { id: "event-1", htmlLink: "" };
    },
    async updateEvent() { calls.push("update"); return { id: "event-1", htmlLink: "" }; },
    async deleteEvent() { calls.push("delete"); },
  };
  const service = new GitHubScheduleSyncService(calendar, state as any);
  const milestone = { number: 4, title: "Launch", dueOn: "2026-09-11T15:00:00Z", state: "open" as const, htmlUrl: "https://github.com/o/r/milestone/4" };
  await Promise.all([
    service.syncMilestone("project", "calendar", "o/r", milestone),
    service.syncMilestone("project", "calendar", "o/r", milestone),
  ]);
  assert.deepEqual(calls, ["create", "update"]);
});

test("closed milestone removes an existing calendar event", async () => {
  const calls: string[] = [];
  const state = new MemoryState();
  const calendar = {
    async createEvent() { return { id: "event-1", htmlLink: "" }; },
    async updateEvent() { return { id: "event-1", htmlLink: "" }; },
    async deleteEvent() { calls.push("delete"); },
  };
  const service = new GitHubScheduleSyncService(calendar, state as any);
  await service.syncMilestone("project", "calendar", "o/r", { number: 3, title: "MVP", dueOn: "2026-09-10T15:00:00Z", state: "open", htmlUrl: "" });
  await service.syncMilestone("project", "calendar", "o/r", { number: 3, title: "MVP", dueOn: null, state: "closed", htmlUrl: "" });
  assert.deepEqual(calls, ["delete"]);
  assert.equal(state.items.size, 0);
});

test("linked issue persists mapping only after issue and calendar creation succeed", async () => {
  const state = new MemoryState();
  const calendar = {
    async createEvent() { return { id: "event-77", htmlLink: "" }; },
    async updateEvent() { return { id: "event-77", htmlLink: "" }; },
    async deleteEvent() {},
  };
  const github = { async createIssue() { return { number: 77, htmlUrl: "https://github.com/o/r/issues/77" }; } };
  const service = new GitHubScheduleSyncService(calendar, state as any);
  const result = await service.createLinkedIssue("project", "calendar", "o/r", {
    title: "로그인 구현", body: "완료 조건", start: "2026-09-01T10:00:00+09:00", end: "2026-09-01T11:00:00+09:00",
  }, github);
  assert.equal(result.issueNumber, 77);
  assert.equal(state.items.size, 1);
  assert.equal([...state.items.values()][0].eventId, "event-77");
});
