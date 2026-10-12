"""Bounded context and safe prompt construction for EEEE's personal secretary lane."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


_SENSITIVE_VALUE = re.compile(
    r"((?:api[_ -]?key|apikey|access[_ -]?token|refresh[_ -]?token|password|비밀번호|토큰|secret)\s*[:=]\s*)[^\s,}\]]+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SecretaryContext:
    conversation_id: str
    recent_turns: list[dict[str, str]]
    preferences: dict[str, str]
    memory_context: str


class PersonalSecretary:
    """Compile the smallest useful personal context for a conversation turn."""

    MAX_TURNS = 12
    MAX_TEXT = 2_000

    def build_prompt(self, text: str, context: SecretaryContext) -> str:
        turns = context.recent_turns[-self.MAX_TURNS :]
        safe_turns = [
            {
                "role": turn.get("role", "unknown"),
                "content": self.redact(turn.get("content", ""))[: self.MAX_TEXT],
            }
            for turn in turns
            if isinstance(turn, dict) and str(turn.get("content", "")).strip()
        ]
        safe_preferences = {
            str(key): self.redact(str(value))[: self.MAX_TEXT]
            for key, value in context.preferences.items()
            if not _SENSITIVE_VALUE.search(f"{key}: {value}")
        }
        safe_memory = self.redact(context.memory_context)[:8_000]
        return (
            "너는 EEEE라는 개인 비서야. 사용자의 현재 요청에 바로 답하고, "
            "최근 대화와 안전하게 보관된 선호를 자연스럽게 반영해. "
            "모르는 내용은 아는 척하지 말고 짧게 되물어. 내부 라우팅·모델·JSON을 설명하지 말고 "
            "자연스러운 한국어로 1~4문장 답해.\n\n"
            f"대화 ID: {context.conversation_id}\n"
            f"최근 대화: {json.dumps(safe_turns, ensure_ascii=False)}\n"
            f"사용자 선호: {json.dumps(safe_preferences, ensure_ascii=False, sort_keys=True)}\n"
            f"관련 기억: {safe_memory}\n"
            f"현재 사용자 요청: {self.redact(text)[:self.MAX_TEXT]}"
        )

    def rememberable_facts(self, text: str) -> list[tuple[str, str]]:
        if _SENSITIVE_VALUE.search(text):
            return []
        normalized = re.sub(r"\s+", " ", text.strip())
        match = re.search(r"나는\s+(아침|오전|점심|오후|저녁|밤)에\s+.*?(?:선호해|좋아해|잘돼)", normalized)
        if match:
            return [("routine.focus_time", match.group(1))]
        return []

    @staticmethod
    def redact(value: str) -> str:
        return _SENSITIVE_VALUE.sub("[REDACTED]", value)
