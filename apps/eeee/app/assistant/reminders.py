from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import sqlite3
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ReminderDraft:
    title: str
    due_at: datetime


@dataclass(frozen=True)
class Reminder:
    id: str
    conversation_id: str
    title: str
    due_at: datetime
    status: str
    created_at: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "conversationId": self.conversation_id,
            "title": self.title,
            "dueAt": self.due_at.isoformat(),
            "status": self.status,
            "createdAt": self.created_at.isoformat(),
        }


_TIME = re.compile(
    r"(?P<day>오늘|내일|모레)?\s*(?P<ampm>오전|오후|저녁|밤)?\s*"
    r"(?P<hour>\d{1,2})(?:시\s*(?P<minute>\d{1,2})?분?|:(?P<colon_minute>\d{2}))"
)
_TRAILING = re.compile(r"(?:\s*(?:일정|약속|리마인더|알림))?\s*(?:등록해줘|추가해줘|알려줘|기억해줘|리마인드해줘|설정해줘)\s*$")
_CREATE_INTENT = ("등록", "추가", "기억해", "알려줘", "리마인드", "설정해")
_QUERY_INTENT = (
    "있는지", "언제인지", "몇 시인지", "몇시인지", "가능한지", "어디인지", "뭐야",
    "시간 알려줘", "언제 알려줘",
)
_KOREA_TZ = ZoneInfo("Asia/Seoul")


def parse_reminder(text: str, *, now: datetime | None = None) -> ReminderDraft | None:
    """Parse only explicit local reminder requests; never guess a missing time."""

    if not any(marker in text for marker in _CREATE_INTENT):
        return None
    if "알려줘" in text and any(marker in text for marker in _QUERY_INTENT):
        return None
    match = _TIME.search(text)
    if match is None:
        return None
    current = now or datetime.now(_KOREA_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    day = match.group("day")
    day_offset = {"오늘": 0, "내일": 1, "모레": 2}.get(day, 0)
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or match.group("colon_minute") or 0)
    ampm = match.group("ampm")
    if ampm in {"오후", "저녁", "밤"} and hour < 12:
        hour += 12
    if ampm == "오전" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    due_at = current.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)
    if day is None and due_at <= current:
        due_at += timedelta(days=1)
    before = text[: match.start()].strip()
    after = _TRAILING.sub("", text[match.end() :]).strip()
    title = " ".join(part for part in (before, after) if part)
    title = re.sub(r"^(?:나|저)?\s*(?:에게|한테)?\s*", "", title)
    title = re.sub(r"^에\s*", "", title).strip(" ,:：")
    if not title or title in {"일정", "약속", "리마인더", "알림"}:
        return None
    return ReminderDraft(title=title, due_at=due_at)


class ReminderStore:
    """Small durable local-first reminder store backed by the EEEE SQLite DB."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS assistant_reminders (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL, due_at TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_assistant_reminders_due "
                "ON assistant_reminders(conversation_id, status, due_at)"
            )
            columns = {row["name"] for row in connection.execute(
                "PRAGMA table_info(assistant_reminders)"
            ).fetchall()}
            if "request_id" not in columns:
                connection.execute(
                    "ALTER TABLE assistant_reminders ADD COLUMN request_id TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_assistant_reminders_request "
                "ON assistant_reminders(conversation_id, request_id) WHERE request_id <> ''"
            )

    def create(self, conversation_id: str, draft: ReminderDraft, *, request_id: str = "") -> Reminder:
        self.init()
        if request_id:
            with self._connect() as connection:
                existing = connection.execute(
                    "SELECT * FROM assistant_reminders WHERE conversation_id = ? AND request_id = ?",
                    (conversation_id, request_id),
                ).fetchone()
            if existing is not None:
                return _from_row(existing)
        reminder = Reminder(
            id=f"reminder-{uuid4().hex}", conversation_id=conversation_id,
            title=draft.title, due_at=draft.due_at,
            status="scheduled", created_at=datetime.now(timezone.utc),
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO assistant_reminders "
                    "(id, conversation_id, request_id, title, due_at, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (reminder.id, reminder.conversation_id, request_id, reminder.title,
                     reminder.due_at.isoformat(), reminder.status, reminder.created_at.isoformat()),
                )
        except sqlite3.IntegrityError:
            if not request_id:
                raise
            with self._connect() as connection:
                existing = connection.execute(
                    "SELECT * FROM assistant_reminders WHERE conversation_id = ? AND request_id = ?",
                    (conversation_id, request_id),
                ).fetchone()
            if existing is None:
                raise
            return _from_row(existing)
        return reminder

    def list(self, conversation_id: str, *, limit: int = 20) -> list[Reminder]:
        self.init()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM assistant_reminders WHERE conversation_id = ? "
                "AND status = 'scheduled' ORDER BY due_at ASC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [_from_row(row) for row in rows]


def _from_row(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=row["id"], conversation_id=row["conversation_id"], title=row["title"],
        due_at=datetime.fromisoformat(row["due_at"]), status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
