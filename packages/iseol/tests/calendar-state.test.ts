import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { CalendarStateStore, calendarExternalKey } from "../src/services/calendar/calendar-state.js";

test("calendar external keys are stable", () => {
  assert.equal(calendarExternalKey("abc", "owner/repo", "issue", 42), "abc:owner/repo:issue:42");
});

test("calendar mappings can be created, updated, and deleted", async () => {
  const dir = await mkdtemp(join(tmpdir(), "iseol-calendar-"));
  const file = join(dir, "state.json");
  const store = new CalendarStateStore(file);
  const key = calendarExternalKey("project", "owner/repo", "issue", 7);

  await store.upsert({ externalKey: key, projectId: "project", calendarId: "cal", eventId: "event-1", source: "issue" });
  assert.equal((await store.find(key))?.eventId, "event-1");

  await store.upsert({ externalKey: key, projectId: "project", calendarId: "cal", eventId: "event-2", source: "issue" });
  assert.equal((await store.find(key))?.eventId, "event-2");

  assert.equal(await store.remove(key), true);
  assert.equal(await store.find(key), null);
  await rm(dir, { recursive: true, force: true });
});

test("calendar state can remove all mappings for a deleted project", async () => {
  const dir = await mkdtemp(join(tmpdir(), "iseol-calendar-cleanup-"));
  const store = new CalendarStateStore(join(dir, "state.json"));
  await store.upsert({ externalKey: "p:a:issue:1", projectId: "p", calendarId: "c", eventId: "1", source: "issue" });
  await store.upsert({ externalKey: "q:a:issue:2", projectId: "q", calendarId: "c", eventId: "2", source: "issue" });
  assert.equal(await store.removeProject("p"), 1);
  assert.equal(await store.find("p:a:issue:1"), null);
  assert.notEqual(await store.find("q:a:issue:2"), null);
  await rm(dir, { recursive: true, force: true });
});

test("calendar state can remove mappings for one manually deleted event", async () => {
  const dir = await mkdtemp(join(tmpdir(), "iseol-calendar-event-cleanup-"));
  const store = new CalendarStateStore(join(dir, "state.json"));
  await store.upsert({ externalKey: "p:a:issue:1", projectId: "p", calendarId: "cal", eventId: "event-deleted", source: "issue" });
  await store.upsert({ externalKey: "p:a:milestone:2", projectId: "p", calendarId: "cal", eventId: "event-other", source: "milestone" });
  await store.upsert({ externalKey: "q:a:issue:3", projectId: "q", calendarId: "cal", eventId: "event-deleted", source: "issue" });

  assert.equal(await store.removeEvent("p", "cal", "event-deleted"), 1);
  assert.equal(await store.find("p:a:issue:1"), null);
  assert.notEqual(await store.find("p:a:milestone:2"), null);
  assert.notEqual(await store.find("q:a:issue:3"), null);
  await rm(dir, { recursive: true, force: true });
});
