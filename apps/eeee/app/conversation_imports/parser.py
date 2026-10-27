"""Strict, text-only parsers for explicit user-owned AI conversation exports.

Never import system/developer instructions, hidden reasoning, tool output,
Codex environment metadata or media. Parsed content remains untrusted.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

MAX_BYTES = 8_000_000
MAX_CONVERSATIONS = 200
MAX_MESSAGES = 500
MAX_TEXT = 15_000


@dataclass(frozen=True)
class ImportedChat:
    provider: str
    source_id: str
    title: str
    messages: list[tuple[str, str]]

    @property
    def digest(self) -> str:
        raw = json.dumps(
            [self.provider, self.title, self.messages],
            ensure_ascii=False, separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_export(provider: str, content: str) -> list[ImportedChat]:
    if provider not in {"chatgpt", "claude", "codex"}:
        raise ValueError("지원하지 않는 내보내기 형식입니다.")
    if not content or len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("파일 크기는 8MB 이하만 지원합니다. 큰 파일은 나누어 주세요.")
    try:
        if provider == "codex":
            parsed = _codex(content)
        else:
            value = json.loads(content)
            parsed = _chatgpt(value) if provider == "chatgpt" else _claude(value)
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("내보내기 파일을 해석할 수 없습니다. 형식을 확인해 주세요.") from exc
    if len(parsed) > MAX_CONVERSATIONS:
        raise ValueError("한 번에 최대 200개 대화까지 읽을 수 있습니다. 파일을 나누어 주세요.")
    return [chat for chat in parsed if chat.messages]


def _text_parts(value) -> str:
    if isinstance(value, str):
        text = value.strip()
        if len(text) > MAX_TEXT:
            raise ValueError("15,000자를 넘는 메시지가 있습니다. 파일을 나누어 주세요.")
        return text
    if not isinstance(value, list):
        return ""
    parts = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") in {
            "text", "input_text", "output_text", "Text",
        } and isinstance(item.get("text"), str):
            parts.append(item["text"])
    text = "\n".join(parts).strip()
    if len(text) > MAX_TEXT:
        raise ValueError("15,000자를 넘는 메시지가 있습니다. 파일을 나누어 주세요.")
    return text


def _chatgpt(data) -> list[ImportedChat]:
    if isinstance(data, dict) and isinstance(data.get("conversations"), list):
        data = data["conversations"]
    if not isinstance(data, list):
        raise TypeError("ChatGPT conversations.json 배열이 아닙니다.")
    output = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("mapping"), dict):
            continue
        mapping = item["mapping"]
        nodes = []
        current = item.get("current_node")
        seen = set()
        if current in mapping:
            while current in mapping and current not in seen:
                seen.add(current)
                node = mapping[current]
                if not isinstance(node, dict):
                    break
                nodes.append(node)
                current = node.get("parent")
            nodes.reverse()
        else:
            # Without a chosen branch, sorting all mapping nodes would mix
            # alternative assistant responses. Do not invent a linear history.
            continue
        messages = []
        for node in nodes:
            message = node.get("message")
            if not isinstance(message, dict):
                continue
            author = message.get("author") or {}
            role = author.get("role")
            if role not in {"user", "assistant"}:
                continue
            metadata = message.get("metadata") or {}
            if metadata.get("is_visually_hidden_from_conversation"):
                continue
            channel = author.get("channel") or message.get("channel") or metadata.get("channel")
            if channel not in {None, "final"}:
                continue
            if role == "assistant" and message.get("recipient") not in {None, "all"}:
                continue
            body = message.get("content") or {}
            if not isinstance(body, dict) or body.get("content_type") not in {
                "text", "multimodal_text",
            }:
                continue
            text = _text_parts(body.get("parts"))
            if text:
                messages.append((role, text))
        source_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "가져온 ChatGPT 대화")[:120]
        if messages:
            if not source_id:
                source_id = hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()
            if len(messages) > MAX_MESSAGES:
                raise ValueError("500개를 넘는 메시지가 있습니다. 대화를 나누어 주세요.")
            output.append(ImportedChat("chatgpt", source_id, title, messages))
    return output


def _claude(data) -> list[ImportedChat]:
    if isinstance(data, dict) and isinstance(data.get("conversations"), list):
        data = data["conversations"]
    if not isinstance(data, list):
        raise TypeError("Claude conversations.json 배열이 아닙니다.")
    output = []
    for item in data:
        if not isinstance(item, dict):
            continue
        messages = []
        for message in item.get("chat_messages", []):
            if not isinstance(message, dict):
                continue
            sender = message.get("sender")
            role = "assistant" if sender in {"assistant", "claude"} else (
                "user" if sender in {"human", "user"} else None
            )
            if role is None:
                continue
            text = _text_parts(message.get("text"))
            if not text:
                text = _text_parts(message.get("content"))
            if text:
                messages.append((role, text))
        if messages:
            title = str(item.get("name") or "가져온 Claude 대화")[:120]
            source_id = str(item.get("uuid") or item.get("id") or "").strip()
            if not source_id:
                source_id = hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()
            if len(messages) > MAX_MESSAGES:
                raise ValueError("500개를 넘는 메시지가 있습니다. 대화를 나누어 주세요.")
            output.append(ImportedChat("claude", source_id, title, messages))
    return output


def _codex(content: str) -> list[ImportedChat]:
    events = []
    replies = []
    session_id = ""
    for line in content.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            continue
        kind, payload = item.get("type"), item.get("payload")
        if not isinstance(payload, dict):
            continue
        if kind == "session_meta":
            session_id = str(payload.get("id") or payload.get("session_id") or "")
        if kind == "event_msg" and payload.get("type") in {"user_message", "agent_message"}:
            role = "user" if payload["type"] == "user_message" else "assistant"
            # Intermediate agent thoughts aren't user-facing outputs.
            if role == "assistant" and payload.get("phase") not in {None, "final_answer"}:
                continue
            text = payload.get("message")
            if isinstance(text, str) and text.strip():
                value = text.strip()
                if len(value) > MAX_TEXT:
                    raise ValueError("15,000자를 넘는 메시지가 있습니다. 파일을 나누어 주세요.")
                events.append((role, value))
        if kind == "event_msg" and payload.get("type") == "item_completed":
            item = payload.get("item")
            if isinstance(item, dict):
                kind_name = item.get("type")
                role = "user" if kind_name == "UserMessage" else (
                    "assistant" if kind_name == "AgentMessage" else None
                )
                if role is not None and (
                    role == "user" or item.get("phase") in {None, "final_answer"}
                ):
                    text = _text_parts(item.get("content"))
                    if text:
                        events.append((role, text))
        if kind == "response_item" and payload.get("type") == "message":
            role = payload.get("role")
            if role not in {"user", "assistant"}:
                continue
            if role == "user":
                metadata = payload.get("internal_chat_message_metadata_passthrough") or {}
                # User role can contain injected AGENTS.md/environment. Only
                # accept the explicit user.text marker in this fallback lane.
                if metadata.get("content_item_kinds") != ["user.text"]:
                    continue
            text = _text_parts(payload.get("content"))
            if text:
                replies.append((role, text))
    # Event messages are explicit visible user and final agent outputs,
    # avoiding duplicated text and internal model messages in response_item.
    messages = events if events else replies
    if not messages:
        return []
    source_id = session_id or hashlib.sha256(content.encode("utf-8")).hexdigest()
    title = f"Codex 작업 · {next((t[:55] for r, t in messages if r == 'user'), '세션')}"
    if len(messages) > MAX_MESSAGES:
        raise ValueError("500개를 넘는 메시지가 있습니다. 대화를 나누어 주세요.")
    return [ImportedChat("codex", source_id, title[:120], messages)]
