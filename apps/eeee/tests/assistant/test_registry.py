import pytest

from app.assistant.models import CapabilityDescriptor
from app.assistant.registry import CapabilityRegistry


def descriptor(capability_id: str = "example") -> CapabilityDescriptor:
    return CapabilityDescriptor(
        id=capability_id,
        version="1.0.0",
        display_name=capability_id,
        intents=[capability_id],
        trigger_phrases=[capability_id],
        required_connectors=[],
        side_effect_level="none",
        approval_level="none",
        claim_latch_policy="claimlatch-v0.2.0",
        memory_writable=True,
    )


def test_registry_registers_and_resolves_a_capability() -> None:
    registry = CapabilityRegistry()
    handler = object()
    registry.register(descriptor(), handler)

    registered = registry.resolve("example")

    assert registered.descriptor.id == "example"
    assert registered.handler is handler
    assert [item.id for item in registry.list()] == ["example"]


def test_registry_rejects_duplicate_and_unknown_capabilities() -> None:
    registry = CapabilityRegistry()
    registry.register(descriptor(), object())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(descriptor(), object())
    with pytest.raises(KeyError, match="unknown"):
        registry.resolve("unknown")


def test_default_registry_contains_the_initial_eeee_capabilities() -> None:
    from app.assistant.registry import build_default_registry

    registry = build_default_registry()

    assert {item.id for item in registry.list()} == {
        "general-conversation",
        "personal-secretary",
        "project-execution",
        "knowledge-documents",
        "presence",
        "user-preference",
    }


def test_registry_can_bind_a_runtime_handler_without_changing_descriptor() -> None:
    registry = CapabilityRegistry()
    metadata = descriptor()
    registry.register(metadata, None)
    handler = object()

    registry.bind("example", handler)

    assert registry.resolve("example").handler is handler
    assert registry.resolve("example").descriptor is metadata
