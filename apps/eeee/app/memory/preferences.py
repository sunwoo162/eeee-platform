"""Small deterministic extractor for explicit user preference statements."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractedPreference:
    key: str
    value: str


_PREFIX = re.compile(r"^(?:기억해줘|기억해|앞으로는|앞으로|항상)\s*", re.I)


def extract_preference(text: str) -> ExtractedPreference | None:
    value = _PREFIX.sub("", " ".join(text.split())).strip(" .!?。！？")
    if value == text.strip(" .!?。！？"):
        return None
    if not value:
        return None
    lowered = value.casefold()
    if "한국어" in value or "한글" in value:
        return ExtractedPreference("language", "한국어")
    if "영어" in value or "english" in lowered:
        return ExtractedPreference("language", "English")
    if "기존 코드" in value or "재사용" in value:
        return ExtractedPreference("implementation.reuse", value)
    if "포트폴리오" in value:
        return ExtractedPreference("quality.portfolio", value)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return ExtractedPreference(f"note.{digest}", value)


def extract_implicit_preference(text: str) -> ExtractedPreference | None:
    """Extract durable, non-sensitive customization decisions only."""

    compact = " ".join(text.split()).strip()
    lowered = compact.casefold()
    if any(secret in lowered for secret in ("api key", "apikey", "비밀번호", "password", "token")):
        return None
    if "포트폴리오" in compact and "플러그인" in compact:
        return ExtractedPreference(
            "architecture.portfolio_delivery",
            "포트폴리오는 EEEE 안정화 후 선택 플러그인으로 추가",
        )
    if "자동으로 기억" in compact or "굳이 기억하라고" in compact:
        return ExtractedPreference(
            "memory.auto_personalization",
            "반복 적용되는 사용자 맞춤 설정과 검증된 작업 패턴은 자동으로 기억",
        )
    if ("기본" in compact or "항상" in compact or "앞으로" in compact) and "한국어" in compact:
        return ExtractedPreference("language", "한국어")
    if ("기본" in compact or "항상" in compact or "앞으로" in compact) and "영어" in compact:
        return ExtractedPreference("language", "English")
    if "사용자는" in compact and ("입력만" in compact or "버튼" in compact):
        return ExtractedPreference(
            "workflow.user_effort",
            "사용자는 짧은 자연어 명령이나 버튼 입력만 하고 나머지는 EEEE가 처리",
        )
    if "플러그인" in compact and ("필요할때" in compact or "필요할 때" in compact):
        return ExtractedPreference(
            "plugins.optional_by_default",
            "플러그인은 필요할 때 연결하고 기본 EEEE 기능과 분리",
        )
    return None
