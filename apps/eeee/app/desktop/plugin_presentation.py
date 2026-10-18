"""Human-readable summaries for structured plugin results."""

from __future__ import annotations

import re
from collections.abc import Mapping


def format_plugin_output(
    plugin_output: Mapping[str, object] | None,
    *,
    action: str | None = None,
) -> str | None:
    """Return a compact, safe summary suitable for the pet speech bubble."""
    if not isinstance(plugin_output, Mapping):
        return None

    effective_action = action or _text(plugin_output.get("action"))
    raw_output = plugin_output.get("output")
    output = raw_output if isinstance(raw_output, Mapping) else plugin_output

    messages = output.get("messages")
    if isinstance(messages, list):
        if not messages:
            return "메일을 찾지 못했어."
        lines = [f"메일 {len(messages)}개를 찾았어."]
        for index, item in enumerate(messages[:5], start=1):
            if not isinstance(item, Mapping):
                continue
            unread = "[안 읽음] " if item.get("isUnread") is True else ""
            subject = _single_line(item.get("subject")) or "(제목 없음)"
            sender = _single_line(item.get("from")) or "보낸 사람 없음"
            snippet = _single_line(item.get("snippet"))
            lines.append(f"{index}. {unread}{subject} · {sender}")
            if snippet:
                lines.append(snippet[:120])
        return "\n".join(lines)

    if output.get("sent") is True or (
        effective_action == "mail.send" and output.get("status") == "completed"
    ):
        return "메일을 보냈어."

    message = _single_line(output.get("message"))
    return message or None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _single_line(value: object) -> str | None:
    text = _text(value)
    return re.sub(r"\s+", " ", text) if text else None
