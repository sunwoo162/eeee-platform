"""The folder and user scope is a data boundary, not cosmetic UI metadata."""
import pytest

from app.chat_scopes.store import WorkspaceStore
from app.conversations.context import ConversationContextBuilder
from app.conversations.models import MessageRole, MessageStatus
from app.conversations.store import ConversationStore
from app.storage.sqlite import SQLiteStore


def make_stores(tmp_path):
    durable = SQLiteStore(tmp_path / "state.sqlite3")
    durable.init()
    return WorkspaceStore(durable), ConversationStore(durable)


def test_project_folder_shares_context_across_own_chats(tmp_path):
    ws, chats = make_stores(tmp_path)
    space = ws.create_workspace("Personal", "personal", user_id="alice")
    project = ws.create_project(space["id"], "Project A", user_id="alice")
    first = chats.create_conversation("Planning", user_id="alice")
    second = chats.create_conversation("Implementation", user_id="alice")
    ws.link_conversation(project["id"], first.id, user_id="alice")
    ws.link_conversation(project["id"], second.id, user_id="alice")

    original = chats.add_message(
        first.id, role=MessageRole.USER, content="We decided on FastAPI",
        status=MessageStatus.COMPLETED,
    )
    memory = ws.add_memory(
        project["id"], "Backend framework: FastAPI", user_id="alice",
        source_message_id=original.id,
    )
    ctx = ConversationContextBuilder(chats)
    ctx.workspace_store = ws
    contents = [m["content"] for m in ctx.build(second.id, user_id="alice")]
    assert any("Backend framework: FastAPI" in m for m in contents)
    assert any("We decided on FastAPI" in m for m in contents)

    ws.revoke_memory(project["id"], memory["id"], user_id="alice")
    contents = [m["content"] for m in ctx.build(second.id, user_id="alice")]
    assert not any("Backend framework: FastAPI" in m for m in contents)
    assert any("We decided on FastAPI" in m for m in contents)


def test_moving_chat_immediately_changes_project_context(tmp_path):
    ws, chats = make_stores(tmp_path)
    space = ws.create_workspace("Personal", "personal", user_id="alice")
    one = ws.create_project(space["id"], "One", user_id="alice")
    two = ws.create_project(space["id"], "Two", user_id="alice")
    chat_a = chats.create_conversation("A", user_id="alice")
    chat_b = chats.create_conversation("B", user_id="alice")
    ws.link_conversation(one["id"], chat_a.id, user_id="alice")
    ws.link_conversation(one["id"], chat_b.id, user_id="alice")
    ws.add_memory(one["id"], "Secret plan for project one", user_id="alice")
    ws.add_memory(two["id"], "Only belongs to project two", user_id="alice")
    builder = ConversationContextBuilder(chats)
    builder.workspace_store = ws
    assert "Secret plan" in str(builder.build(chat_b.id, user_id="alice"))
    ws.link_conversation(two["id"], chat_b.id, user_id="alice")
    content = str(builder.build(chat_b.id, user_id="alice"))
    assert "Only belongs" in content
    assert "Secret plan" not in content
    assert len(ws.list_conversations(one["id"], user_id="alice")) == 1


def test_no_cross_user_transcript_leak_even_in_team_folder(tmp_path):
    ws, chats = make_stores(tmp_path)
    space = ws.create_workspace("Team", "team", user_id="alice")
    project = ws.create_project(space["id"], "Shared", user_id="alice")
    alice_chat = chats.create_conversation("Private", user_id="alice")
    ws.link_conversation(project["id"], alice_chat.id, user_id="alice")
    chats.add_message(
        alice_chat.id, role=MessageRole.USER,
        content="PRIVATE_ALICE_TRANSCRIPT", status=MessageStatus.COMPLETED,
    )
    ws.add_member(space["id"], "bob", "editor", user_id="alice")
    bob_chat = chats.create_conversation("My chat", user_id="bob")
    ws.link_conversation(project["id"], bob_chat.id, user_id="bob")
    ws.add_memory(project["id"], "Approved team design: SQLite", user_id="alice")
    assert [row["id"] for row in ws.list_conversations(project["id"], user_id="bob")] == [bob_chat.id]
    context = str(ws.context_items(bob_chat.id, user_id="bob"))
    assert "Approved team design" in context
    assert "PRIVATE_ALICE_TRANSCRIPT" not in context
    with pytest.raises(KeyError):
        ws.link_conversation(project["id"], alice_chat.id, user_id="bob")


def test_viewers_cannot_write_and_personal_cannot_add_members(tmp_path):
    ws, chats = make_stores(tmp_path)
    private = ws.create_workspace("Personal", "personal", user_id="alice")
    with pytest.raises(ValueError):
        ws.add_member(private["id"], "bob", "viewer", user_id="alice")
    shared = ws.create_workspace("Team", "team", user_id="alice")
    project = ws.create_project(shared["id"], "Alpha", user_id="alice")
    ws.add_member(shared["id"], "bob", "viewer", user_id="alice")
    with pytest.raises(PermissionError):
        ws.create_project(shared["id"], "Unauthorized", user_id="bob")
    with pytest.raises(PermissionError):
        ws.add_memory(project["id"], "Unauthorized", user_id="bob")
    with pytest.raises(PermissionError):
        ws.link_conversation(project["id"], chats.create_conversation(user_id="bob").id, user_id="bob")


def test_upgrade_is_idempotent_and_links_survive_restart(tmp_path):
    ws, chats = make_stores(tmp_path)
    space = ws.create_workspace("Personal", "personal", user_id="alice")
    project = ws.create_project(space["id"], "Durable", user_id="alice")
    chat = chats.create_conversation("Remember", user_id="alice")
    ws.link_conversation(project["id"], chat.id, user_id="alice")
    ws2, _ = make_stores(tmp_path)
    assert ws2.project_for_conversation(chat.id, user_id="alice")["id"] == project["id"]
    assert ws2.list_projects(space["id"], user_id="alice")[0]["name"] == "Durable"

def test_existing_memory_store_cannot_leak_project_specific_facts(tmp_path):
    from app.memory.store import MemoryStore

    ws, chats = make_stores(tmp_path)
    space = ws.create_workspace("Personal", "personal", user_id="alice")
    first = ws.create_project(space["id"], "Alpha", user_id="alice")
    second = ws.create_project(space["id"], "Beta", user_id="alice")
    chat = chats.create_conversation("Beta chat", user_id="alice")
    ws.link_conversation(second["id"], chat.id, user_id="alice")

    memories = MemoryStore(tmp_path / "state.sqlite3")
    alpha = memories.save_user_preference(
        "alpha-secret", "PRIVATE_ALPHA_PROJECT_VALUE",
        scope={"projectId": first["id"]}, user_id="alice",
    )
    memories.save_user_preference(
        "beta-choice", "BETA_ONLY_VALUE",
        scope={"projectId": second["id"]}, user_id="alice",
    )
    memories.save_user_preference(
        "global-style", "PREFER_SHORT_ANSWERS", user_id="alice",
    )
    builder = ConversationContextBuilder(chats, memory_store=memories)
    builder.workspace_store = ws
    for ids in (None, [alpha.id]):
        content = str(builder.build(chat.id, user_id="alice", memory_ids=ids))
        assert "PRIVATE_ALPHA_PROJECT_VALUE" not in content
    actual = str(builder.build(chat.id, user_id="alice"))
    assert "BETA_ONLY_VALUE" in actual
    assert "PREFER_SHORT_ANSWERS" in actual
