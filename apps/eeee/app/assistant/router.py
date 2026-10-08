from __future__ import annotations

import re

from app.assistant.models import (
    AssistantRequest,
    CapabilityCandidate,
    CapabilitySelection,
)
from app.assistant.registry import CapabilityRegistry


class CapabilityRouter:
    """Select the best registered EEEE capability without hidden side effects."""

    MINIMUM_SCORE = 1
    OPTIONAL_PLUGIN_HINTS = (
        ("notion", "Notion", ["pages.read", "pages.write"]),
        ("노션", "Notion", ["pages.read", "pages.write"]),
        ("google calendar", "Google Calendar", ["calendar.read", "calendar.write"]),
        ("구글 캘린더", "Google Calendar", ["calendar.read", "calendar.write"]),
        ("github", "GitHub", ["repository.read", "repository.write"]),
        ("깃허브", "GitHub", ["repository.read", "repository.write"]),
        ("slack", "Slack", ["messages.read", "messages.write"]),
        ("슬랙", "Slack", ["messages.read", "messages.write"]),
    )

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def select(self, request: AssistantRequest) -> CapabilitySelection:
        if request.requested_capability is not None:
            registered = self.registry.resolve(request.requested_capability)
            return CapabilitySelection(
                status="selected",
                capability_id=registered.descriptor.id,
                candidates=[
                    CapabilityCandidate(
                        capability_id=registered.descriptor.id,
                        score=1,
                        reasons=["explicit capability request"],
                    )
                ],
                reasons=["selected by explicit capability request"],
            )

        normalized = _normalize(request.raw_text)
        candidates: list[CapabilityCandidate] = []
        for descriptor in self.registry.list():
            matched = [phrase for phrase in descriptor.trigger_phrases if _contains(normalized, phrase)]
            score = len(matched)
            if score:
                candidates.append(
                    CapabilityCandidate(
                        capability_id=descriptor.id,
                        score=score,
                        reasons=[f"matched trigger: {phrase}" for phrase in matched],
                    )
                )

        candidates.sort(key=lambda item: (-item.score, item.capability_id))
        hint = self._optional_plugin_hint(normalized)
        if hint is not None and not any(
            candidate.capability_id.startswith(f"plugin:{hint[0]}:") for candidate in candidates
        ):
            plugin_id, plugin_name, permissions = hint
            return CapabilitySelection(
                status="plugin_required",
                reasons=[f"Optional plugin is required: {plugin_id}"],
                required_plugin_id=plugin_id,
                required_plugin_name=plugin_name,
                required_plugin_permissions=permissions,
                suggested_action=f"{plugin_name} 플러그인을 설치하고 연결해줘",
            )
        if not candidates:
            if any(
                phrase in normalized
                for phrase in ("이거", "저거", "해줘", "해 줘", "do it", "that")
            ):
                candidates = [
                    CapabilityCandidate(
                        capability_id=descriptor.id,
                        score=0,
                        reasons=["no trigger matched"],
                    )
                    for descriptor in self.registry.list()
                ]
                return CapabilitySelection(
                    status="needs_clarification",
                    candidates=candidates,
                    reasons=["The request needs a clearer action or subject"],
                )
            fallback = self.registry.resolve("general-conversation")
            return CapabilitySelection(
                status="selected",
                capability_id=fallback.descriptor.id,
                candidates=[CapabilityCandidate(
                    capability_id=fallback.descriptor.id,
                    score=0,
                    reasons=["default EEEE conversation fallback"],
                )],
                reasons=["No specialized capability matched; EEEE handles the conversation"],
            )

        if candidates[0].score < self.MINIMUM_SCORE:
            if not candidates:
                candidates = [
                    CapabilityCandidate(
                        capability_id=descriptor.id,
                        score=0,
                        reasons=["no trigger matched"],
                    )
                    for descriptor in self.registry.list()
                ]
            return CapabilitySelection(
                status="needs_clarification",
                candidates=candidates,
                reasons=["No registered capability reached the routing threshold"],
            )

        winner = candidates[0]
        return CapabilitySelection(
            status="selected",
            capability_id=winner.capability_id,
            candidates=candidates,
            reasons=winner.reasons,
        )

    def _optional_plugin_hint(self, normalized: str) -> tuple[str, str, list[str]] | None:
        for phrase, plugin_name, permissions in self.OPTIONAL_PLUGIN_HINTS:
            if _contains(normalized, phrase):
                plugin_id = phrase if phrase.isascii() else {
                    "노션": "notion", "구글 캘린더": "google-calendar",
                    "깃허브": "github", "슬랙": "slack",
                }[phrase]
                return plugin_id, plugin_name, permissions
        return None


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _contains(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = _normalize(phrase)
    if not normalized_phrase:
        return False
    if normalized_phrase.isascii():
        # English triggers are words, not substrings ("app" is not "happy").
        return re.search(r"(?<![a-z0-9_])" + re.escape(normalized_phrase) + r"(?![a-z0-9_])", normalized_text) is not None
    return normalized_phrase in normalized_text
