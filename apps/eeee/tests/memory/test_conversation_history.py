from pathlib import Path

from app.agent.protocol import AgentResult
from app.assistant.router import CapabilityRouter
from app.assistant.service import AssistantService
from app.config import Settings
from app.coordinator.service import Coordinator
from app.memory.store import MemoryStore
from app.project_runtime.provisioner import ProjectProvisioner
from app.storage.sqlite import SQLiteStore
from app.assistant.registry import build_default_registry


def test_memory_store_persists_recent_conversation_turns(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "state.sqlite3")
    store.init()

    store.append_conversation_turn("desktop-default", "user", "내 고양이 이름은 모찌야.")
    store.append_conversation_turn("desktop-default", "assistant", "모찌라고 기억할게.")

    turns = store.recent_conversation_turns("desktop-default", limit=4)

    assert turns == [
        {"role": "user", "content": "내 고양이 이름은 모찌야."},
        {"role": "assistant", "content": "모찌라고 기억할게."},
    ]


def test_memory_store_exposes_paginated_chat_history_with_metadata(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "state.sqlite3")
    store.init()

    store.append_conversation_turn("desktop-default", "user", "첫 번째 명령")
    store.append_conversation_turn("desktop-default", "assistant", "첫 번째 답변")
    store.append_conversation_turn("desktop-default", "user", "두 번째 명령")
    store.append_conversation_turn("desktop-default", "assistant", "두 번째 답변")

    page = store.get_conversation_turns("desktop-default", limit=2)

    assert page["conversationId"] == "desktop-default"
    assert [turn["content"] for turn in page["turns"]] == ["두 번째 명령", "두 번째 답변"]
    assert page["turns"][0]["role"] == "user"
    assert page["turns"][0]["createdAt"]
    assert page["nextBeforeId"] is not None

    older = store.get_conversation_turns(
        "desktop-default", limit=2, before_id=page["nextBeforeId"]
    )
    assert [turn["content"] for turn in older["turns"]] == ["첫 번째 명령", "첫 번째 답변"]
    assert older["nextBeforeId"] is None


def test_memory_store_lists_conversations_without_exposing_other_memory_rows(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "state.sqlite3")
    store.init()

    store.append_conversation_turn("desktop-default", "user", "EEEE에게 보낸 명령")
    store.append_conversation_turn("desktop-default", "assistant", "Ollama 답변")
    store.append_conversation_turn("another-chat", "user", "별도 대화")

    conversations = store.list_conversations(limit=10)

    assert [item["conversationId"] for item in conversations] == [
        "another-chat", "desktop-default",
    ]
    desktop = next(item for item in conversations if item["conversationId"] == "desktop-default")
    assert desktop["messageCount"] == 2
    assert desktop["preview"] == "Ollama 답변"
    assert desktop["updatedAt"]


def test_general_conversation_receives_recent_turns_without_explicit_remember_request(tmp_path: Path) -> None:
    class ConversationRuntime:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def run(self, request):
            self.prompts.append(request.prompt)
            return AgentResult(
                status="completed",
                summary="기억하고 이어서 답할게.",
                events=[],
                changed_files=[],
                test_commands=[],
                error=None,
            )

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path / "workspaces")
    store = SQLiteStore(settings.data_dir / "state.sqlite3")
    store.init()
    coordinator = Coordinator(store)
    runtime = ConversationRuntime()
    service = AssistantService(
        router=CapabilityRouter(build_default_registry()),
        coordinator=coordinator,
        store=store,
        settings=settings,
        provisioner=ProjectProvisioner(store),
        agent_runtime=runtime,
    )

    service.route("내 고양이 이름은 모찌야.")
    service.route("내 고양이 이름이 뭐였지?")

    assert len(runtime.prompts) == 2
    assert "내 고양이 이름은 모찌야." in runtime.prompts[1]
    assert "기억하고 이어서 답할게." in runtime.prompts[1]
