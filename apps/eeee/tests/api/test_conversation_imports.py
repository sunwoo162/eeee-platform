"""Import previews and commits never automatically convert foreign text into memory."""
import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.conversation_imports.parser import parse_export
from app.main import create_app


def chatgpt_document():
    return [{
        "id": "chat-export-1", "title": "API 설계",
        "current_node": "a2",
        "mapping": {
            "root": {"parent": None, "message": None},
            "u": {"parent": "root", "message": {
                "author": {"role": "user"}, "content": {
                    "content_type": "text", "parts": ["REST 구조 설명해 줘"],
                },
            }},
            "a1": {"parent": "u", "message": {
                "author": {"role": "assistant"}, "content": {
                    "content_type": "text", "parts": ["old branch"],
                },
            }},
            "a2": {"parent": "u", "message": {
                "author": {"role": "assistant"}, "content": {
                    "content_type": "text", "parts": ["최종 대답"],
                },
            }},
            "system": {"parent": "root", "message": {
                "author": {"role": "system"}, "content": {
                    "content_type": "text", "parts": ["secret system prompt"],
                },
            }},
        },
    }]


def test_chatgpt_branch_no_hidden_messages():
    result = parse_export("chatgpt", json.dumps(chatgpt_document(), ensure_ascii=False))
    assert len(result) == 1
    assert result[0].messages == [
        ("user", "REST 구조 설명해 줘"),
        ("assistant", "최종 대답"),
    ]


def test_claude_import_filters_nonchat_material():
    source = [{
        "uuid": "claude-xyz", "name": "UI 참고",
        "chat_messages": [
            {"sender": "human", "text": "버튼 스타일 알려줘"},
            {"sender": "assistant", "content": [{"type": "text", "text": "파란 버튼"}]},
            {"sender": "tool", "text": "unsafe tool result"},
        ],
    }]
    result = parse_export("claude", json.dumps(source, ensure_ascii=False))
    assert result[0].messages == [
        ("user", "버튼 스타일 알려줘"), ("assistant", "파란 버튼"),
    ]


def test_codex_import_prefers_user_visible_events_to_injected_context():
    rows = [
        {"type": "session_meta", "payload": {"id": "session-1", "cwd": "/secret"}},
        {"type": "response_item", "payload": {
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "injected AGENTS.md"}],
        }},
        {"type": "event_msg", "payload": {
            "type": "user_message", "message": "버그 찾아줘",
        }},
        {"type": "event_msg", "payload": {
            "type": "agent_message", "message": "내부 초안", "phase": "analysis",
        }},
        {"type": "event_msg", "payload": {
            "type": "agent_message", "message": "버그 수정 확인", "phase": "final_answer",
        }},
        {"type": "response_item", "payload": {
            "type": "function_call", "command": "cat ~/.ssh/id_rsa",
        }},
    ]
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    result = parse_export("codex", text)
    assert result[0].messages == [
        ("user", "버그 찾아줘"), ("assistant", "버그 수정 확인"),
    ]


def test_preview_confirm_dedup_and_project_memory_approval(tmp_path):
    app = create_app(Settings(
        data_dir=tmp_path / "data", workspace_root=tmp_path / "work",
    ))
    client = TestClient(app)
    w = client.post("/v1/workspaces", json={"name": "개인", "kind": "personal"}).json()["id"]
    p = client.post(f"/v1/workspaces/{w}/projects", json={"name": "프로젝트"}).json()["id"]
    original = client.post(f"/v1/projects/{p}/conversations", json={"title": "일반 채팅"}).json()["id"]
    payload = {"provider": "chatgpt", "content": json.dumps(chatgpt_document(),ensure_ascii=False)}
    before = client.post("/v1/imports/preview", json=payload)
    assert before.status_code == 200, before.text
    assert before.json()["items"][0]["messageCount"] == 2
    assert len(client.get("/v1/conversations").json()["items"]) == 1

    committed = client.post("/v1/imports/commit", json={
        **payload, "selectedIndexes": [0], "projectId": p,
    })
    assert committed.status_code == 200, committed.text
    imported = committed.json()["imported"]
    assert len(imported) == 1
    imported_chat = imported[0]["conversationId"]
    assert len(client.get(f"/v1/conversations/{imported_chat}/messages").json()["items"]) == 2
    origin = client.get(f"/v1/imports/conversations/{imported_chat}/origin").json()["origin"]
    assert origin["source_id"] == "chat-export-1"
    assert origin["provider"] == "chatgpt"

    repeated = client.post("/v1/imports/commit", json={
        **payload, "selectedIndexes": [0], "projectId": p,
    })
    assert repeated.json()["imported"] == []
    assert repeated.json()["skipped"][0]["reason"] == "duplicate"

    # Imported chats can be viewed but do not enter other sibling contexts.
    project_context = app.state.workspace_store.context_items(original, user_id="local-user")
    assert not any("REST 구조" in row["content"] for row in project_context)
    assert app.state.workspace_store.list_memories(p, user_id="local-user") == []

    first_msg_id = client.get(f"/v1/conversations/{imported_chat}/messages").json()["items"][0]["id"]
    saved = client.post(f"/v1/projects/{p}/memories", json={
        "content": "API 설계에서 REST 사용", "source_message_id": first_msg_id,
    })
    assert saved.status_code == 201, saved.text
    project_context = app.state.workspace_store.context_items(original, user_id="local-user")
    assert any("API 설계에서 REST 사용" in row["content"] for row in project_context)


def test_import_foreign_user_and_invalid_project_rejected(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data",workspace_root=tmp_path / "work"))
    client = TestClient(app)
    w = client.post("/v1/workspaces",json={"name":"Mine"}).json()["id"]
    p = client.post(f"/v1/workspaces/{w}/projects",json={"name":"Private"}).json()["id"]
    payload = {
        "provider": "chatgpt", "content": json.dumps(chatgpt_document()),
        "selectedIndexes": [0], "projectId": p,
    }
    blocked = client.post("/v1/imports/commit",json=payload,headers={"X-EEEE-User-Id":"intruder"})
    assert blocked.status_code in {403,404}
    assert client.get("/v1/conversations").json()["items"] == []
    assert client.post("/v1/imports/commit",json={**payload,"selectedIndexes":[1]}).status_code == 400
    assert client.post("/v1/imports/preview",json={
        "provider":"chatgpt","content":"{}",
    }).status_code == 400
    assert client.post("/v1/imports/preview",json={
        "provider":"chatgpt","content":payload["content"],
    },headers={"origin":"https://untrusted.example"}).status_code == 403


def test_modern_codex_completed_items_skip_tools_and_reasoning():
    rows = [
        {"type": "session_meta", "payload": {"id": "modern-session"}},
        {"type": "event_msg", "payload": {
            "type": "item_completed", "item": {
                "type": "UserMessage",
                "content": [{"type": "text", "text": "안전하게 구현해줘"}],
            },
        }},
        {"type": "event_msg", "payload": {
            "type": "item_completed", "item": {
                "type": "ToolCall",
                "content": [{"type": "text", "text": "SECRET"}],
            },
        }},
        {"type": "event_msg", "payload": {
            "type": "item_completed", "item": {
                "type": "AgentMessage", "phase": "final_answer",
                "content": [{"type": "Text", "text": "완료했어"}],
            },
        }},
    ]
    result = parse_export("codex", "\n".join(json.dumps(x) for x in rows))
    assert result[0].messages == [
        ("user", "안전하게 구현해줘"), ("assistant", "완료했어"),
    ]


def test_import_rejects_oversize_message_instead_of_silent_truncation():
    document = chatgpt_document()
    document[0]["mapping"]["u"]["message"]["content"]["parts"] = ["s" * 15001]
    import pytest
    with pytest.raises(ValueError, match="15,000"):
        parse_export("chatgpt", json.dumps(document))


def test_chatgpt_skips_hidden_internal_channel_and_tool_recipient():
    source = chatgpt_document()
    mapping = source[0]["mapping"]
    mapping["hidden"] = {"parent": "u", "message": {
        "author": {"role": "assistant", "channel": "analysis"},
        "content": {"content_type": "text", "parts": ["private analysis"]},
    }}
    mapping["tool"] = {"parent": "hidden", "message": {
        "author": {"role": "assistant"}, "recipient": "python",
        "content": {"content_type": "text", "parts": ["print(secret)"]},
    }}
    mapping["a2"]["parent"] = "tool"
    output = parse_export("chatgpt", json.dumps(source, ensure_ascii=False))
    assert output[0].messages == [
        ("user", "REST 구조 설명해 줘"), ("assistant", "최종 대답"),
    ]
