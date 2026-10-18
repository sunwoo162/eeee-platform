"""Deterministic input extraction for connected plugin actions.

The router chooses the capability. This module only turns the user's text
into provider input after that choice has been made; it does not choose a
provider or perform any side effect.
"""

from __future__ import annotations

import re


_EMAIL = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)


def build_plugin_action_input(plugin_id: str, action: str, text: str) -> dict[str, object]:
    if plugin_id == "gmail" and action == "mail.list":
        return _gmail_list_input(text)
    if plugin_id == "gmail" and action == "mail.send":
        return _gmail_send_input(text)
    return {}


def _gmail_list_input(text: str) -> dict[str, object]:
    value: dict[str, object] = {}
    count = re.search(r"(?<!\d)(\d{1,2})\s*(?:개|건|통)", text)
    value["limit"] = int(count.group(1)) if count else 10
    if any(marker in text.casefold() for marker in ("안 읽", "미읽", "unread")):
        value["query"] = "is:unread"
    return value


def _gmail_send_input(text: str) -> dict[str, object]:
    recipient = _EMAIL.search(text)
    if recipient is None:
        raise ValueError("메일을 보내려면 받는 사람 이메일 주소가 필요해")

    subject = _capture(text, r"(?:제목|subject)\s*(?:은|는|이|가|:)?\s*(.+?)(?=\s*(?:본문|내용|body)\s*(?:은|는|이|가|:)?|\s*(?:메일을?|이메일을?)?\s*(?:보내|전송)|$)")
    body = _capture(text, r"(?:본문|내용|body)\s*(?:은|는|이|가|:)?\s*(.+?)(?=\s*(?:메일을?|이메일을?)?\s*(?:보내|전송)|$)")

    if not subject and not body:
        shorthand = re.search(
            r"\b[\w.+\-]+@[\w.\-]+\.[A-Za-z]{2,}\s*(?:에|로)\s*(.+?)\s*라는\s*(?:메일|이메일)",
            text,
            re.IGNORECASE,
        )
        if shorthand:
            subject = body = shorthand.group(1).strip()

    if not subject and body:
        subject = body[:80]
    if not body and subject:
        body = subject
    if not subject or not body:
        raise ValueError("메일을 보내려면 제목과 본문을 알려줘")
    return {"to": recipient.group(0), "subject": subject, "body": body}


def _capture(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if match is None:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip(" \t\r\n.,")
    return value or None
