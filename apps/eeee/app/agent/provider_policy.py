"""Deterministic provider selection for EEEE's general assistant lane."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


ProviderName = Literal["local", "web", "builtin", "unavailable"]


@dataclass(frozen=True)
class ProviderDecision:
    provider: ProviderName
    reason: Literal[
        "simple_request", "complex_or_tool_request", "local_unavailable",
        "web_unavailable", "web_primary", "builtin_fallback", "no_provider_available",
    ]


class ProviderPolicy:
    """Choose a provider without letting provider availability change intent."""

    _COMPLEX_MARKERS = (
        "프로젝트", "앱", "서비스", "개발", "구현", "만들어", "코드", "파일",
        "플러그인", "노션", "깃허브", "일정", "달력", "todo", "build", "create",
        "implement", "code", "file", "plugin", "github", "notion", "calendar",
    )
    _BUILTIN_INTENT_PATTERNS = tuple(
        re.compile(pattern)
        for pattern in (
            r"(?:안녕|안녕하세요|안녕하십니까|하이|hello|hi|반가워|반갑습니다)",
            r"안녕 오늘 기분이 어때",
            r"(?:고마워|고마워요|고맙습니다|감사해|감사해요|감사합니다|thanks|thank you)",
            r"(?:지금 )?(?:뭐해|뭐 해|뭐 하고 있어|어디야|상태(?:가|는)?(?: 어때)?|잘 지내(?:요)?)",
            r"(?:너는 |넌 |무엇을 |뭐를 |뭘 )?(?:어느 정도까지 )?(?:할 수 있어|할수 있어|가능해|뭐 할 수 있어|무엇을 할 수 있어|what can you do|what are you capable of|capable)",
            r"(?:ㅇㅇ|응|네|알겠어|알겠습니다|오케이|좋아|좋아요|확인|확인했어|확인했습니다|okay|ok)(?: (?:ㅇㅇ|응|네|알겠어|알겠습니다|오케이|좋아|좋아요|확인|확인했어|확인했습니다|okay|ok))*",
            r"(?:(?:오늘|요즘|지금) )?(?:내 )?기분(?:이|은|가|는) (?:(?:조금|좀) )?(?:어때|좋아|괜찮아|가라앉았어|우울해|힘들어|피곤해|속상해|심심해)",
            r"(?:나|저)(?:는|도)? (?:(?:조금|좀) )?(?:힘들어|피곤해|우울해|속상해|심심해|괜찮아|좋아|행복해)",
            r"(?:이야기|얘기|대화)(?:하자|하고 싶어|하고 싶어요|할래|해줘)|(?:말하고 싶어|말하고 싶어요)",
            r"(?:왜 말 안 해|왜 대답 안 해|벙어리야|말해줘)",
            r"(?:i am|i'm|im|i feel) (?:happy|sad|fine|good|okay|tired|lonely|upset)",
        )
    )

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = re.sub(r"[!?.,~]+", " ", text.casefold())
        return re.sub(r"\s+", " ", normalized).strip()

    @classmethod
    def is_builtin_eligible(cls, text: str) -> bool:
        """Return whether the deterministic provider can answer this turn safely."""

        normalized = cls._normalize(text)
        if not normalized:
            return False
        return any(pattern.fullmatch(normalized) for pattern in cls._BUILTIN_INTENT_PATTERNS)

    def choose(
        self, text: str, *, local_available: bool, web_available: bool,
        builtin_available: bool = False,
    ) -> ProviderDecision:
        normalized = self._normalize(text)
        complex_request = any(marker in normalized for marker in self._COMPLEX_MARKERS)
        builtin_eligible = builtin_available and self.is_builtin_eligible(text)
        if complex_request:
            if web_available:
                return ProviderDecision("web", "complex_or_tool_request")
            if local_available:
                return ProviderDecision("local", "web_unavailable")
        else:
            if web_available:
                return ProviderDecision("web", "web_primary")
            if local_available:
                return ProviderDecision("local", "simple_request")
            if builtin_eligible:
                return ProviderDecision("builtin", "builtin_fallback")
        if local_available:
            return ProviderDecision("local", "web_unavailable")
        if web_available:
            return ProviderDecision("web", "local_unavailable")
        if builtin_eligible:
            return ProviderDecision("builtin", "builtin_fallback")
        return ProviderDecision("unavailable", "no_provider_available")
