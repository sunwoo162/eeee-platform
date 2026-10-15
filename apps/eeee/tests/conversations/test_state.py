import pytest

from app.conversations.models import RequestState
from app.conversations.state import InvalidRequestTransition, validate_request_transition


def test_request_state_machine_allows_generation_to_streaming_to_completed() -> None:
    validate_request_transition(RequestState.RECEIVED, RequestState.PERSISTED_USER_MESSAGE)
    validate_request_transition(RequestState.PERSISTED_USER_MESSAGE, RequestState.CLASSIFIED)
    validate_request_transition(RequestState.CLASSIFIED, RequestState.GENERATING)
    validate_request_transition(RequestState.GENERATING, RequestState.STREAMING)
    validate_request_transition(RequestState.STREAMING, RequestState.COMPLETED)


def test_request_state_machine_rejects_terminal_state_changes() -> None:
    with pytest.raises(InvalidRequestTransition):
        validate_request_transition(RequestState.COMPLETED, RequestState.STREAMING)
