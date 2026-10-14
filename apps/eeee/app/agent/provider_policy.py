"""Deterministic provider selection for EEEE's general assistant lane."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


ProviderName = Literal["local", "web", "unavailable"]


@dataclass(frozen=True)
class ProviderDecision:
    provider: ProviderName
    reason: Literal[
        "simple_request", "complex_or_tool_request", "local_unavailable",
        "web_unavailable", "no_provider_available",
    ]


class ProviderPolicy:
    """Choose a provider without letting provider availability change intent."""

    _COMPLEX_MARKERS = (
        "프로젝트", "앱", "서비스", "개발", "구현", "만들어", "코드", "파일",
        "플러그인", "노션", "깃허브", "일정", "달력", "todo", "build", "create",
        "implement", "code", "file", "plugin", "github", "notion", "calendar",
    )

    def choose(
        self, text: str, *, local_available: bool, web_available: bool
    ) -> ProviderDecision:
        normalized = re.sub(r"\s+", " ", text.casefold()).strip()
        complex_request = any(marker in normalized for marker in self._COMPLEX_MARKERS)
        if complex_request:
            if web_available:
                return ProviderDecision("web", "complex_or_tool_request")
            if local_available:
                return ProviderDecision("local", "web_unavailable")
        else:
            if local_available:
                return ProviderDecision("local", "simple_request")
            # Ordinary conversation is a local-only lane. Do not silently
            # promote it to the slower Web/GPT lane when local AI is absent.
            # The caller must surface the unavailable state instead.
            if web_available:
                return ProviderDecision("unavailable", "local_unavailable")
        if local_available:
            return ProviderDecision("local", "web_unavailable")
        if web_available:
            return ProviderDecision("web", "local_unavailable")
        return ProviderDecision("unavailable", "no_provider_available")
