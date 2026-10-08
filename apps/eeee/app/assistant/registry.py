from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from app.assistant.models import CapabilityDescriptor


@dataclass(frozen=True)
class RegisteredCapability:
    descriptor: CapabilityDescriptor
    handler: Any


class CapabilityRegistry:
    """Runtime registry for EEEE capabilities and their opaque handlers."""

    def __init__(self) -> None:
        self._capabilities: dict[str, RegisteredCapability] = {}
        self._dynamic_provider: Callable[[], list[CapabilityDescriptor]] | None = None

    def register(self, descriptor: CapabilityDescriptor, handler: Any) -> None:
        if descriptor.id in self._capabilities:
            raise ValueError(f"Capability already registered: {descriptor.id}")
        self._capabilities[descriptor.id] = RegisteredCapability(descriptor, handler)

    def list(self) -> list[CapabilityDescriptor]:
        descriptors = [item.descriptor for item in self._capabilities.values()]
        if self._dynamic_provider is not None:
            descriptors.extend(self._dynamic_provider())
        return descriptors

    def resolve(self, capability_id: str) -> RegisteredCapability:
        try:
            return self._capabilities[capability_id]
        except KeyError as exc:
            if self._dynamic_provider is not None:
                for descriptor in self._dynamic_provider():
                    if descriptor.id == capability_id:
                        return RegisteredCapability(descriptor, None)
            raise KeyError(f"Unknown capability: {capability_id}") from exc

    def set_dynamic_provider(self, provider: Callable[[], list[CapabilityDescriptor]] | None) -> None:
        """Project ephemeral capabilities such as currently healthy plugins."""
        self._dynamic_provider = provider

    def bind(self, capability_id: str, handler: Any) -> None:
        """Attach a runtime implementation while retaining the registered policy."""
        registered = self.resolve(capability_id)
        self._capabilities[capability_id] = RegisteredCapability(registered.descriptor, handler)


def _descriptor(
    capability_id: str,
    display_name: str,
    intents: list[str],
    trigger_phrases: list[str],
    *,
    required_connectors: list[str] | None = None,
    side_effect_level: str = "none",
    approval_level: str = "none",
    memory_writable: bool = False,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        id=capability_id,
        version="1.0.0",
        display_name=display_name,
        intents=intents,
        trigger_phrases=trigger_phrases,
        required_connectors=required_connectors or [],
        side_effect_level=side_effect_level,  # type: ignore[arg-type]
        approval_level=approval_level,  # type: ignore[arg-type]
        claim_latch_policy="claimlatch-v0.2.0",
        memory_writable=memory_writable,
    )


def build_default_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        _descriptor(
            "general-conversation",
            "EEEE General Assistant",
            ["conversation", "question", "assistant"],
            ["안녕", "고마워", "뭐해", "어때", "hello", "hi", "thanks", "how are you"],
        ),
        None,
    )
    registry.register(
        _descriptor(
            "user-preference",
            "User Preference Memory",
            ["preference", "memory", "personalization"],
            ["기억해줘", "기억해", "앞으로는", "앞으로", "remember", "from now on"],
            memory_writable=True,
        ),
        None,
    )
    registry.register(
        _descriptor(
            "personal-secretary",
            "Personal Secretary",
            ["schedule", "reminder", "routine"],
            ["일정", "달력", "캘린더", "약속", "회의", "리마인더", "calendar", "schedule", "remind"],
        ),
        None,
    )
    registry.register(
        _descriptor(
            "project-execution",
            "Project Execution",
            ["project", "development", "build"],
            ["프로젝트", "앱", "서비스", "기능", "개발", "만들어", "구현", "todo", "할 일", "체크리스트", "project", "app", "build", "develop"],
            side_effect_level="local",
            memory_writable=True,
        ),
        None,
    )
    registry.register(
        _descriptor(
            "portfolio-generation",
            "Portfolio Generation",
            ["portfolio", "retrospective", "resume", "interview"],
            ["포트폴리오", "기술 블로그", "이력서", "면접 설명", "회고", "portfolio", "resume", "retrospective", "interview"],
            side_effect_level="local",
        ),
        None,
    )
    registry.register(
        _descriptor(
            "knowledge-documents",
            "Knowledge and Documents",
            ["document", "knowledge", "search"],
            ["문서", "파일", "정리", "요약", "기억", "검색", "document", "file", "summarize", "memory"],
            memory_writable=True,
        ),
        None,
    )
    registry.register(
        _descriptor(
            "presence",
            "Presence",
            ["desktop", "mobile", "notification"],
            ["바탕화면", "위젯", "휴대폰", "모바일", "desktop", "widget", "mobile", "phone"],
            side_effect_level="local",
        ),
        None,
    )
    return registry
