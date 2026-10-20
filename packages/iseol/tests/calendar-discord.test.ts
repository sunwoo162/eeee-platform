import assert from "node:assert/strict";
import test from "node:test";
import { parseCalendarCustomId, parseKstDateTime, calendarPanelDescription } from "../src/services/calendar/calendar-discord.js";

test("calendar custom ids identify project and action", () => {
  assert.deepEqual(parseCalendarCustomId("calendar:add:abc123"), { action: "add", projectId: "abc123" });
  assert.equal(parseCalendarCustomId("other:add:abc123"), null);
});

test("calendar date parser accepts local minute input and rejects invalid values", () => {
  assert.equal(parseKstDateTime("2026-09-01 14:30"), "2026-09-01T14:30:00+09:00");
  assert.throws(() => parseKstDateTime("2026-09-01"), /YYYY-MM-DD HH:mm/);
});

test("calendar panel copy stays compact", () => {
  const text = calendarPanelDescription("https://calendar.google.com/test");
  assert.match(text, /일정 추가/);
  assert.match(text, /Google Calendar/);
  assert.ok(text.length < 500);
});

import { parseRepositorySide } from "../src/services/calendar/calendar-discord.js";

test("github issue repository selector accepts frontend or backend only", () => {
  assert.equal(parseRepositorySide(" FRONTEND "), "frontend");
  assert.equal(parseRepositorySide("backend"), "backend");
  assert.throws(() => parseRepositorySide("api"), /frontend 또는 backend/);
});
