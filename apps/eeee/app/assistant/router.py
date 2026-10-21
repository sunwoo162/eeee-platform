from __future__ import annotations

import re
from collections.abc import Callable

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
        ("gmail", "Gmail", ["mail.read", "mail.send"]),
        ("지메일", "Gmail", ["mail.read", "mail.send"]),
        ("google calendar", "Google Calendar", ["calendar.read", "calendar.write"]),
        ("구글 캘린더", "Google Calendar", ["calendar.read", "calendar.write"]),
        ("google drive", "Google Drive", ["files.read", "files.write"]),
        ("구글 드라이브", "Google Drive", ["files.read", "files.write"]),
        ("google contacts", "Google Contacts", ["contacts.read"]),
        ("구글 연락처", "Google Contacts", ["contacts.read"]),
        ("github", "GitHub", ["repos.read", "issues.read", "pull_requests.write"]),
        ("깃허브", "GitHub", ["repos.read", "issues.read", "pull_requests.write"]),
        ("figma", "Figma", ["files.read", "files.write"]),
        ("피그마", "Figma", ["files.read", "files.write"]),
        ("slack", "Slack", ["messages.read", "messages.write"]),
        ("슬랙", "Slack", ["messages.read", "messages.write"]),
        ("linear", "Linear", ["issues.read", "issues.write"]),
        ("리니어", "Linear", ["issues.read", "issues.write"]),
        ("todoist", "Todoist", ["tasks.read", "tasks.write"]),
        ("투두이스트", "Todoist", ["tasks.read", "tasks.write"]),
        ("outlook mail", "Outlook Email", ["mail.read", "mail.send"]),
        ("아웃룩 메일", "Outlook Email", ["mail.read", "mail.send"]),
        ("outlook calendar", "Outlook Calendar", ["calendar.read", "calendar.write"]),
        ("아웃룩 캘린더", "Outlook Calendar", ["calendar.read", "calendar.write"]),
    )

    OPTIONAL_PLUGIN_IDS = {
        "notion": "notion", "노션": "notion", "gmail": "gmail", "지메일": "gmail",
        "google calendar": "google-calendar", "구글 캘린더": "google-calendar",
        "google drive": "google-drive", "구글 드라이브": "google-drive",
        "google contacts": "google-contacts", "구글 연락처": "google-contacts",
        "github": "github", "깃허브": "github", "figma": "figma", "피그마": "figma",
        "slack": "slack", "슬랙": "slack", "linear": "linear", "리니어": "linear",
        "todoist": "todoist", "투두이스트": "todoist",
        "outlook mail": "outlook-email", "아웃룩 메일": "outlook-email",
        "outlook calendar": "outlook-calendar", "아웃룩 캘린더": "outlook-calendar",
    }

    def __init__(
        self,
        registry: CapabilityRegistry,
        plugin_status_provider: Callable[[str], str] | None = None,
    ) -> None:
        self.registry = registry
        self.plugin_status_provider = plugin_status_provider

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
        if _is_explicit_knowledge_command(normalized):
            documents = self.registry.resolve("knowledge-documents")
            return CapabilitySelection(
                status="selected",
                capability_id=documents.descriptor.id,
                candidates=[CapabilityCandidate(
                    capability_id=documents.descriptor.id,
                    score=100,
                    reasons=["explicit local document command"],
                )],
                reasons=["explicit local document command"],
            )
        if _is_informational_capability_question(normalized):
            fallback = self.registry.resolve("general-conversation")
            return CapabilitySelection(
                status="selected",
                capability_id=fallback.descriptor.id,
                candidates=[CapabilityCandidate(
                    capability_id=fallback.descriptor.id,
                    score=0,
                    reasons=["informational capability question"],
                )],
                reasons=["informational capability question"],
            )
        candidates: list[CapabilityCandidate] = []
        for descriptor in self.registry.list():
            matched = [phrase for phrase in descriptor.trigger_phrases if _contains(normalized, phrase)]
            specific_matches = [
                phrase for phrase in matched
                if not any(
                    phrase != other
                    and _normalize(phrase) in _normalize(other)
                    for other in matched
                )
            ]
            score = sum(1 + len(_normalize(phrase)) // 3 for phrase in specific_matches)
            score += _action_intent_bonus(descriptor.id, normalized)
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
        if hint is not None and _is_plugin_action_request(normalized) and not any(
            candidate.capability_id.startswith(f"plugin:{hint[0]}:") for candidate in candidates
        ):
            plugin_id, plugin_name, permissions = hint
            return CapabilitySelection(
                status="plugin_required",
                reasons=[f"Optional plugin is required: {plugin_id}"],
                required_plugin_id=plugin_id,
                required_plugin_name=plugin_name,
                required_plugin_permissions=permissions,
                suggested_action=self._plugin_suggested_action(plugin_id, plugin_name),
            )
        if not candidates:
            if any(
                phrase in normalized
                for phrase in ("이거", "저거", "do it", "that")
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

    def _plugin_suggested_action(self, plugin_id: str, plugin_name: str) -> str:
        status = "not_installed"
        if self.plugin_status_provider is not None:
            try:
                status = self.plugin_status_provider(plugin_id)
            except (KeyError, RuntimeError):
                status = "not_installed"
        if status == "not_installed":
            return f"{plugin_name} 플러그인을 설치해줘"
        return f"{plugin_name} 플러그인 계정을 연결해줘"

    def _optional_plugin_hint(self, normalized: str) -> tuple[str, str, list[str]] | None:
        for phrase, plugin_name, permissions in self.OPTIONAL_PLUGIN_HINTS:
            if _contains(normalized, phrase):
                plugin_id = self.OPTIONAL_PLUGIN_IDS[phrase]
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


def _is_informational_capability_question(normalized: str) -> bool:
    """Keep capability/about-me questions out of side-effectful work routes."""
    question_markers = (
        "할 수 있어", "할수 있어", "어느 정도", "어느정도", "가능해", "가능하",
        "뭐 할 수", "무엇을 할 수", "어떤 걸 할 수", "어떤 작업", "도와줄 수",
        "지원해", "뭐가 가능", "뭐야", "뭐가", "무엇", "어떤", "무슨", "어떻게",
        "만들 수 있어", "만들수 있어", "저장되어", "저장돼",
        "방법", "설명해", "에 대해", "기능", "연결되어", "연결돼",
        "연동되어", "연동돼", "설치되어", "설치돼", "can you", "what can you",
        "how capable", "what do you support", "are you able",
    )
    if not any(marker in normalized for marker in question_markers):
        return False
    return not _is_action_request(normalized)


def _is_action_request(normalized: str) -> bool:
    """Recognize imperative requests without treating explanatory wording as an action."""
    action_endings = (
        "해줘", "해 줘", "해주세요", "해 주세요", "해", "줘", "주세요",
    )
    action_verbs = (
        "만들어", "만들", "구현", "생성", "작성", "개발", "보내", "전송",
        "읽어", "읽", "찾아", "찾", "검색", "조회", "확인", "가져", "다운로드",
        "업로드", "연결", "설치", "동기화", "저장", "정리", "요약", "추가",
        "등록", "수정", "삭제", "열어", "보여", "예약", "취소", "build",
        "create", "implement", "develop", "generate", "send", "read", "find",
        "search", "show", "get", "install", "connect", "save", "update", "delete",
    )
    return any(
        normalized.endswith(verb + ending)
        or f" {verb}{ending}" in normalized
        for verb in action_verbs
        for ending in action_endings
    )


def _is_plugin_action_request(normalized: str) -> bool:
    """Only turn a plugin hint into an installation request for an actual operation."""
    return (
        _is_action_request(normalized)
        or any(normalized.endswith(ending) for ending in ("해줘", "해 줘", "해주세요", "해 주세요", "줘", "주세요"))
        or any(
            marker in normalized
            for marker in (
                "보내", "전송", "읽", "찾", "검색", "조회", "확인", "가져", "다운로드",
                "업로드", "연결", "설치", "동기화", "저장", "정리", "요약", "검색",
                "send", "read", "find", "search", "list", "show", "get", "install",
                "connect", "save", "update", "delete",
            )
        )
    )


def _is_explicit_knowledge_command(normalized: str) -> bool:
    """Give an explicit document command precedence over broad project words."""
    return re.match(
        r"^(?:문서\s*)?(?:저장|검색|찾아|조회|보여|요약)(?:해줘|해|하기|줘)?(?:\s*[:：]|\s*$)",
        normalized,
    ) is not None


def _action_intent_bonus(capability_id: str, normalized: str) -> int:
    """Prefer the action verb over a broad provider noun match.

    For example, "Gmail에 메일 보내" contains both the broad "메일" trigger
    and the more specific send intent. The capability id is metadata owned by
    the connector, so this stays provider-agnostic.
    """
    action = capability_id.rsplit(":", 1)[-1].casefold()
    write_markers = (
        "보내", "전송", "작성", "생성", "추가", "등록", "수정", "삭제",
        "send", "create", "write", "update", "delete", "add",
    )
    read_markers = (
        "목록", "조회", "찾", "읽", "보여", "확인", "list", "search",
        "read", "show", "find", "get",
    )
    if any(marker in normalized for marker in write_markers):
        return 4 if any(marker in action for marker in ("send", "create", "write", "update", "delete", "add")) else 0
    if any(marker in normalized for marker in read_markers):
        return 3 if any(marker in action for marker in ("list", "search", "read", "get", "events")) else 0
    return 0
