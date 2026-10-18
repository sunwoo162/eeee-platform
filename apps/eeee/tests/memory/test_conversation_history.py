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


def test_memory_store_lists_searches_and_pages_conversation_turns(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "state.sqlite3")
    store.init()

    store.append_conversation_turn("desktop-default", "user", "첫 명령")
    store.append_conversation_turn("desktop-default", "assistant", "첫 답변")
    store.append_conversation_turn("desktop-default", "user", "두 번째 명령")
    store.append_conversation_turn("other", "user", "다른 대화")

    conversations = store.list_conversations(limit=10)
    assert [item["conversationId"] for item in conversations] == ["other", "desktop-default"]
    assert conversations[1]["messageCount"] == 3
    assert conversations[1]["preview"] == "두 번째 명령"

    search = store.search_conversations("첫 답변", limit=10)
    assert [item["conversationId"] for item in search] == ["desktop-default"]

    latest = store.get_conversation("desktop-default", limit=2)
    assert [item["content"] for item in latest["turns"]] == ["첫 답변", "두 번째 명령"]
    assert latest["nextBeforeId"] is not None

    older = store.get_conversation(
        "desktop-default", limit=2, before_id=latest["nextBeforeId"]
    )
    assert [item["content"] for item in older["turns"]] == ["첫 명령"]


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
