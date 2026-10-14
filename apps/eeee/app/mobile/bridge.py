from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from app.storage.connection import connect_sqlite


class MobileBridgeError(RuntimeError):
    """The local Desktop↔Mobile pairing or authorization contract failed."""


class MobileBridge:
    """Durable pairing plus short-lived live events for a paired mobile client.

    The bridge stores only hashes of pairing codes and device tokens. It does not
    become a hosted service: the Desktop process owns the database and the
    Mobile app talks to this process over an explicitly paired local route.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        enabled: bool = True,
        pairing_ttl_seconds: int = 600,
        event_limit: int = 200,
    ) -> None:
        self.database_path = Path(database_path)
        self.enabled = enabled
        self.pairing_ttl_seconds = pairing_ttl_seconds
        self.event_limit = event_limit
        self._lock = Lock()
        self._events: list[dict[str, Any]] = []
        self._cursor = 0

    def init(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS mobile_pairing (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    pairing_code_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mobile_devices (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS mobile_events (
                    cursor INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._cursor = connection.execute(
                "SELECT COALESCE(MAX(cursor), 0) FROM mobile_events"
            ).fetchone()[0]

    def issue_pairing_code(self) -> dict[str, str]:
        self._require_enabled()
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = _utc_now() + timedelta(seconds=self.pairing_ttl_seconds)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO mobile_pairing (id, pairing_code_hash, expires_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET pairing_code_hash = excluded.pairing_code_hash, "
                "expires_at = excluded.expires_at",
                (_hash_secret(code), _iso(expires_at)),
            )
        return {"code": code, "expiresAt": _iso(expires_at)}

    def pair(self, pairing_code: str, device_name: str) -> dict[str, str]:
        self._require_enabled()
        if not pairing_code.isdigit() or len(pairing_code) != 6:
            raise MobileBridgeError("Invalid mobile pairing code")
        if not device_name.strip():
            raise MobileBridgeError("Mobile device name is required")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT pairing_code_hash, expires_at FROM mobile_pairing WHERE id = 1"
            ).fetchone()
            if row is None or not hmac.compare_digest(row["pairing_code_hash"], _hash_secret(pairing_code)):
                raise MobileBridgeError("Invalid mobile pairing code")
            if _parse_iso(row["expires_at"]) <= _utc_now():
                raise MobileBridgeError("Mobile pairing code has expired")
            device_id = "mobile-" + uuid4().hex
            token = secrets.token_urlsafe(32)
            connection.execute(
                "INSERT INTO mobile_devices (device_id, device_name, token_hash, created_at) "
                "VALUES (?, ?, ?, ?)",
                (device_id, device_name.strip(), _hash_secret(token), _iso(_utc_now())),
            )
        self.publish("mobile.paired", {"deviceId": device_id, "deviceName": device_name.strip()})
        return {"deviceId": device_id, "deviceName": device_name.strip(), "accessToken": token}

    def authorize(self, token: str | None) -> dict[str, str]:
        self._require_enabled()
        if not token:
            raise MobileBridgeError("Mobile bridge token is required")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT device_id, device_name, token_hash FROM mobile_devices WHERE revoked_at IS NULL"
            ).fetchall()
        token_hash = _hash_secret(token)
        for row in rows:
            if hmac.compare_digest(row["token_hash"], token_hash):
                return {"deviceId": row["device_id"], "deviceName": row["device_name"]}
        raise MobileBridgeError("Mobile bridge token is invalid or revoked")

    def revoke(self, device_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE mobile_devices SET revoked_at = ? WHERE device_id = ?",
                (_iso(_utc_now()), device_id),
            )
        self.publish("mobile.revoked", {"deviceId": device_id})

    def publish(self, kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            created_at = _iso(_utc_now())
            with self._connect() as connection:
                self._cursor = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(cursor), 0) + 1 FROM mobile_events"
                    ).fetchone()[0]
                )
                connection.execute(
                    "INSERT INTO mobile_events (cursor, kind, payload_json, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (self._cursor, kind, json.dumps(dict(payload), ensure_ascii=False), created_at),
                )
                connection.execute(
                    "DELETE FROM mobile_events WHERE cursor <= ?",
                    (self._cursor - self.event_limit,),
                )
            event = {
                "cursor": self._cursor,
                "kind": kind,
                "payload": dict(payload),
                "createdAt": created_at,
            }
            self._events.append(event)
            if len(self._events) > self.event_limit:
                self._events = self._events[-self.event_limit :]
            return event

    def events_after(self, cursor: int = 0) -> dict[str, Any]:
        with self._lock:
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        "SELECT cursor, kind, payload_json, created_at FROM mobile_events "
                        "WHERE cursor > ? ORDER BY cursor ASC LIMIT ?",
                        (cursor, self.event_limit),
                    ).fetchall()
                events = [
                    {
                        "cursor": row["cursor"],
                        "kind": row["kind"],
                        "payload": json.loads(row["payload_json"]),
                        "createdAt": row["created_at"],
                    }
                    for row in rows
                ]
            except sqlite3.OperationalError:
                events = [event for event in self._events if event["cursor"] > cursor]
            return {
                "cursor": self._cursor,
                "events": events,
            }

    def status(self) -> dict[str, Any]:
        with self._connect() as connection:
            device_count = connection.execute(
                "SELECT COUNT(*) FROM mobile_devices WHERE revoked_at IS NULL"
            ).fetchone()[0]
        return {
            "transport": "desktop-bridge",
            "enabled": self.enabled,
            "pairedDevices": device_count,
            "realtime": "sse-or-polling",
        }

    def _connect(self) -> sqlite3.Connection:
        connection = connect_sqlite(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise MobileBridgeError("Mobile bridge is disabled")


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)
