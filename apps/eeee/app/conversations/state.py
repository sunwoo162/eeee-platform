from __future__ import annotations

from app.conversations.models import RequestState


class InvalidRequestTransition(ValueError):
    """Raised when a request attempts an illegal lifecycle transition."""


_TRANSITIONS: dict[RequestState, frozenset[RequestState]] = {
    RequestState.RECEIVED: frozenset({RequestState.PERSISTED_USER_MESSAGE, RequestState.FAILED, RequestState.CANCELLED}),
    RequestState.PERSISTED_USER_MESSAGE: frozenset({RequestState.CLASSIFIED, RequestState.FAILED, RequestState.CANCELLED}),
    RequestState.CLASSIFIED: frozenset({
        RequestState.GENERATING,
        RequestState.AWAITING_APPROVAL,
        RequestState.FAILED,
        RequestState.CANCELLED,
    }),
    RequestState.GENERATING: frozenset({
        RequestState.STREAMING,
        RequestState.FAILED,
        RequestState.CANCELLED,
        RequestState.INTERRUPTED,
    }),
    RequestState.AWAITING_APPROVAL: frozenset({
        RequestState.EXECUTING,
        RequestState.CANCELLED,
        RequestState.FAILED,
    }),
    RequestState.EXECUTING: frozenset({
        RequestState.STREAMING,
        RequestState.COMPLETED,
        RequestState.FAILED,
        RequestState.CANCELLED,
        RequestState.INTERRUPTED,
    }),
    RequestState.STREAMING: frozenset({
        RequestState.COMPLETED,
        RequestState.FAILED,
        RequestState.CANCELLED,
        RequestState.INTERRUPTED,
    }),
}


def validate_request_transition(current: RequestState, target: RequestState) -> None:
    if target not in _TRANSITIONS.get(current, frozenset()):
        raise InvalidRequestTransition(f"Cannot transition request from {current} to {target}")
