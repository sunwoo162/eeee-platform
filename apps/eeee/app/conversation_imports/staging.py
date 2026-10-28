"""Bounded, in-process upload staging for local AI transcript ZIP imports.

Never extract files to the filesystem. Only selected transcript entries are
decoded. Staging data expires and is removed when the Core stops.
"""
from __future__ import annotations

import io
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import uuid4

from app.conversation_imports.parser import ImportedChat, parse_export

MAX_ARCHIVE_BYTES = 64_000_000
MAX_TEXT_BYTES = 48_000_000
MAX_TOTAL_EXTRACTED = 64_000_000
MAX_ZIP_MEMBERS = 2048
MAX_STAGED_CHATS = 1000
MAX_ACTIVE_UPLOADS = 3
EXPIRY_SECONDS = 1800


@dataclass
class StagedImport:
    id: str
    owner: str
    provider: str
    chats: list[ImportedChat]
    created_at: float


class ImportStaging:
    def __init__(self) -> None:
        self._sessions: dict[str, StagedImport] = {}
        self._lock = threading.RLock()

    def _clean(self) -> None:
        expired = [
            key for key, session in self._sessions.items()
            if time.monotonic() - session.created_at >= EXPIRY_SECONDS
        ]
        for key in expired:
            del self._sessions[key]

    def create(self, *, owner: str, provider: str, data: bytes, filename: str) -> StagedImport:
        if not data or len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError("Upload must be between 1 byte and 64 MB")
        if provider not in {"chatgpt", "claude", "codex"}:
            raise ValueError("Unsupported provider")
        if filename.lower().endswith(".zip"):
            chats = parse_archive(provider, data)
        elif filename.lower().endswith((".json", ".jsonl")):
            try:
                content = data.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError("Transcript must be UTF-8") from exc
            chats = parse_export(
                provider, content, max_bytes=MAX_TEXT_BYTES,
                max_conversations=MAX_STAGED_CHATS,
            )
        else:
            raise ValueError("Supported formats are .zip, .json and .jsonl")
        if len(chats) > MAX_STAGED_CHATS:
            raise ValueError("Archive has too many conversations")
        with self._lock:
            self._clean()
            owned = sum(s.owner == owner for s in self._sessions.values())
            if owned >= MAX_ACTIVE_UPLOADS:
                raise ValueError("Maximum 3 active previews; restart or complete one")
            session = StagedImport(
                id=f"import-stage-{uuid4().hex}", owner=owner, provider=provider,
                chats=chats, created_at=time.monotonic(),
            )
            self._sessions[session.id] = session
            return session

    def get(self, session_id: str, *, owner: str) -> StagedImport:
        with self._lock:
            self._clean()
            session = self._sessions.get(session_id)
            if session is None or session.owner != owner:
                raise KeyError("Import preview unavailable or expired")
            return session

    def release(self, session_id: str, *, owner: str) -> None:
        with self._lock:
            session = self.get(session_id, owner=owner)
            self._sessions.pop(session.id, None)

    def shutdown(self) -> None:
        with self._lock:
            self._sessions.clear()


def parse_archive(provider: str, data: bytes) -> list[ImportedChat]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("Archive is not a valid ZIP") from exc
    chats: list[ImportedChat] = []
    with archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_MEMBERS:
            raise ValueError("ZIP contains too many files")
        total_uncompressed = 0
        selected = []
        for info in members:
            path = PurePosixPath(info.filename.replace("\\", "/"))
            if (
                path.is_absolute() or ".." in path.parts or
                (path.parts and ":" in path.parts[0]) or
                info.flag_bits & 0x1 or info.is_dir()
            ):
                # Ignore unrelated directories but reject unsafe entries.
                if info.is_dir() and not path.is_absolute() and ".." not in path.parts:
                    continue
                raise ValueError("ZIP contains unsafe or encrypted entry")
            if provider == "codex":
                matched = path.suffix.lower() == ".jsonl"
            else:
                matched = path.name.lower() == "conversations.json"
            if not matched:
                continue
            if info.file_size > MAX_TEXT_BYTES:
                raise ValueError("Transcript entry is too large")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_TOTAL_EXTRACTED:
                raise ValueError("ZIP transcript payload is too large")
            selected.append(info)
        if provider != "codex" and len(selected) != 1:
            raise ValueError("ZIP must contain exactly one conversations.json")
        if provider == "codex" and len(selected) > 64:
            raise ValueError("ZIP has too many Codex sessions")
        if not selected:
            raise ValueError("No supported transcripts found in ZIP")
        for info in selected:
            try:
                with archive.open(info) as entry:
                    # Validate actual inflated size, not just ZIP metadata.
                    raw = entry.read(MAX_TEXT_BYTES + 1)
                    if len(raw) > MAX_TEXT_BYTES or entry.read(1):
                        raise ValueError("ZIP entry exceeded uncompressed size limit")
            except (zipfile.BadZipFile, RuntimeError, EOFError, OSError) as exc:
                raise ValueError("ZIP transcript entry is damaged or unsupported") from exc
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError("ZIP transcript must be UTF-8") from exc
            chats.extend(parse_export(
                provider, text, max_bytes=MAX_TEXT_BYTES,
                max_conversations=MAX_STAGED_CHATS,
            ))
            if len(chats) > MAX_STAGED_CHATS:
                raise ValueError("Too many conversations in ZIP")
    if not chats:
        raise ValueError("No readable text conversations were found")
    return chats


def preview_page(session: StagedImport, *, offset: int = 0, limit: int = 40) -> dict:
    if offset < 0 or limit < 1 or limit > 50:
        raise ValueError("Invalid pagination")
    page = session.chats[offset:offset + limit]
    return {
        "sessionId": session.id,
        "total": len(session.chats),
        "offset": offset,
        "items": [
            {
                "index": i + offset, "provider": chat.provider, "title": chat.title,
                "messageCount": len(chat.messages),
                "excerpt": next((text[:160] for role, text in chat.messages if role == "user"), ""),
            } for i, chat in enumerate(page)
        ],
    }
