from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class PetPresentation:
    state: str
    expression: str
    headline: str
    detail: str
    show_approval: bool
    blocked: bool
    runtime_profile: str | None = None
    quality_status: str | None = None
    deployment_readiness: str | None = None
    missing_connectors: tuple[str, ...] = ()

    @classmethod
    def from_view_model(cls, payload: dict[str, object]) -> "PetPresentation":
        state = payload.get("state")
        message = payload.get("message")
        detail = message if isinstance(message, str) and message else "The project state is unavailable."
        expressions = {
            "idle": ("sleepy", "Ready"),
            "researching": ("curious", "Researching"),
            "awaiting_approval": ("thinking", "Approval needed"),
            "working": ("focused", "Working"),
            "verifying": ("checking", "Verifying"),
            "completed": ("happy", "Completed"),
            "blocked": ("alert", "Blocked"),
            "failed": ("worried", "Failed"),
        }
        if not isinstance(state, str) or state not in expressions:
            return cls(
                state="blocked",
                expression="confused",
                headline="Blocked",
                detail=detail,
                show_approval=False,
                blocked=True,
            )
        expression, headline = expressions[state]
        profile = payload.get("projectProfile")
        profile = profile if isinstance(profile, dict) else {}
        runtime_profile = profile.get("runtimeProfile")
        runtime_profile = runtime_profile if isinstance(runtime_profile, str) else None
        quality_status = payload.get("qualityStatus")
        quality_status = quality_status if isinstance(quality_status, str) else None
        connectors = profile.get("connectors", [])
        missing_connectors = tuple(
            str(connector.get("connectorId"))
            for connector in connectors
            if isinstance(connector, dict)
            and connector.get("state") == "awaiting_configuration"
            and isinstance(connector.get("connectorId"), str)
        ) if isinstance(connectors, list) else ()
        deployment_readiness = profile.get("provisioningStatus")
        deployment_readiness = (
            deployment_readiness if isinstance(deployment_readiness, str) else None
        )
        if deployment_readiness is None and missing_connectors:
            deployment_readiness = "awaiting_configuration"
        return cls(
            state=state,
            expression=expression,
            headline=headline,
            detail=detail,
            show_approval=state == "awaiting_approval",
            blocked=False,
            runtime_profile=runtime_profile,
            quality_status=quality_status,
            deployment_readiness=deployment_readiness,
            missing_connectors=missing_connectors,
        )


@dataclass(frozen=True)
class BubbleGeometry:
    width: int
    height: int
    lines: int


class BubbleLayout:
    """Measure text separately from the decorative bubble asset area."""

    def __init__(
        self,
        *,
        max_width: int = 420,
        min_width: int = 160,
        horizontal_padding: int = 48,
        vertical_padding: int = 32,
        line_height: int = 28,
        average_char_width: int = 14,
    ) -> None:
        self.max_width = max_width
        self.min_width = min_width
        self.horizontal_padding = horizontal_padding
        self.vertical_padding = vertical_padding
        self.line_height = line_height
        self.average_char_width = average_char_width

    def measure(self, text: str) -> BubbleGeometry:
        lines = text.splitlines() or [""]
        content_width = max(1, self.max_width - self.horizontal_padding)
        chars_per_line = max(1, content_width // self.average_char_width)
        wrapped_lines = sum(
            max(1, ceil(max(len(line), 1) / chars_per_line)) for line in lines
        )
        longest_line = max((len(line) for line in lines), default=1)
        width = min(
            self.max_width,
            max(
                self.min_width,
                min(content_width, longest_line * self.average_char_width)
                + self.horizontal_padding,
            ),
        )
        return BubbleGeometry(
            width=width,
            height=wrapped_lines * self.line_height + self.vertical_padding,
            lines=wrapped_lines,
        )


@dataclass(frozen=True)
class ConversationPresentation:
    state: str
    text: str
    visible: bool = True

    @classmethod
    def for_input(cls, text: str = "") -> "ConversationPresentation":
        return cls("input", text)

    @classmethod
    def for_submission(cls, text: str) -> "ConversationPresentation":
        return cls("submitting", text)

    @classmethod
    def for_stream(cls, text: str) -> "ConversationPresentation":
        return cls("streaming", text)

    @classmethod
    def for_answer(cls, text: str) -> "ConversationPresentation":
        return cls("answer", text)

    @classmethod
    def for_error(cls, text: str) -> "ConversationPresentation":
        return cls("error", text)

    @classmethod
    def hidden(cls) -> "ConversationPresentation":
        return cls("hidden", "", visible=False)
